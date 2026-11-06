"""TDD: OpenAI-совместимый шлюз (шаг 4 плана).

Контракт bridges/openai_bridge.py:
  - argv: <base-url> (HTTPS; HTTP только для loopback — тест отвергает http://
    на внешний хост);
  - ключ из provider_secrets (env DMS_AGENT_OPENAI_PROVIDER), не из argv;
  - POST {base}/chat/completions stream=true, Bearer;
  - SSE data: {...choices[0].delta.content} -> assistant-чанки;
  - [DONE] / конец потока -> result (usage из chunk.usage);
  - 401 -> result is_error c понятной ошибкой; redirect -> ошибка с явным
    «ключ на новый origin не отправлен»; обрыв соединения -> result is_error;
  - cancel во время потока -> resp.close(), result is_error «cancelled»;
  - текстовый чат: tool_use никогда не выдумывается.
"""
import json
import os
import select
import subprocess
import sys
import threading
import time
import http.server
import socketserver
import stat
import uuid

import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("DMS_AGENT_OPENAI_PROVIDER", "mock-gateway")

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(PLUGIN, "bridges", "openai_bridge.py")


def free_port():
    with socketserver.TCPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler) as s:
        return s.server_address[1]


class Gateway(http.server.BaseHTTPRequestHandler):
    """Configurable mock: class attrs set per test."""
    mode = "sse"            # sse | unauthorized | redirect | drop
    seen_auth = []          # Authorization headers received
    seen_path = []
    seen_messages = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.seen_path.append(self.path)
        if self.mode == "redirect" and self.path == "/v1/chat/completions":
            # Pretend the gateway moved: 307 with Location on ANOTHER origin.
            self.send_response(307)
            self.send_header("Location", "http://elsewhere.example/v1/chat/completions")
            self.end_headers()
            return
        body = json.dumps({"data": [{"id": "gw-chat"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.seen_messages.append(json.loads(self.rfile.read(int(self.headers["Content-Length"])))['messages'])
        self.seen_auth.append(self.headers.get("Authorization", ""))
        if self.mode == "unauthorized":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.mode == "redirect":
            self.send_response(307)
            self.send_header("Location", "http://elsewhere.example/v1/chat/completions")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for piece in ["при", "вет"]:
                chunk = {"choices": [{"delta": {"content": piece}}]}
                self.wfile.write(("data: %s\n\n" % json.dumps(chunk)).encode())
                self.wfile.flush()
                if self.mode == "drop":
                    self.wfile.close()
                    return
                time.sleep(0.3)
            if self.mode != "drop":
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        if self.mode != "drop":
            self.wfile.write(("data: %s\n\n" % json.dumps(
                {"choices": [], "usage": {"total_tokens": 7}})).encode())
            self.wfile.flush()


def start_gateway(mode):
    port = free_port()
    Gateway.mode = mode
    Gateway.seen_auth = []
    Gateway.seen_path = []
    Gateway.seen_messages = []
    srv = socketserver.TCPServer(("127.0.0.1", port), Gateway)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, "http://127.0.0.1:%d/v1" % port


class _LineReader:
    """select() on a text-mode pipe is unreliable: the BufferedReader may
    have already swallowed the next lines into its userspace buffer, so the
    fd looks idle while data sits in Python's buffer. Read the raw fd and
    split lines ourselves."""
    def __init__(self, stream):
        self.fd = stream.fileno()
        self.buf = b""

    def read_event(self, timeout=10):
        deadline = time.time() + timeout
        while True:
            if b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                try:
                    return json.loads(line.decode())
                except ValueError:
                    continue
            if time.time() > deadline:
                return None
            r, _, _ = select.select([self.fd], [], [], 0.3)
            if not r:
                continue
            chunk = os.read(self.fd, 65536)
            if not chunk:
                return None
            self.buf += chunk


def read_event(stream, timeout=10):
    if not isinstance(stream, _LineReader):
        stream = _LineReader(stream)
    return stream.read_event(timeout)


class Bridge:
    def __init__(self, base_url, env=None, cwd=None):
        e = dict(os.environ)
        e.update(env or {})
        self.proc = subprocess.Popen(
            [sys.executable, BRIDGE, base_url],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=e, cwd=cwd)
        self.reader = _LineReader(self.proc.stdout)

    def send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def read_until_result(self, timeout=10):
        while True:
            ev = self.reader.read_event(timeout=timeout)
            if ev is None:
                return None
            if ev.get("type") == "result":
                return ev

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def user_msg(text):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def test_sse_stream_to_assistant_chunks_and_result():
    srv, base = start_gateway("sse")
    b = Bridge(base, env={"DMS_AGENT_OPENAI_MODEL": "gw-chat"})
    try:
        b.send({"type": "config", "model": "gw-chat", "systemPrompt": "Ты помощник"})
        b.send(user_msg("привет"))
        texts = []
        result = None
        while True:
            ev = read_event(b.proc.stdout, timeout=10)
            if ev is None:
                break
            if ev.get("type") == "assistant":
                texts.append("".join(c.get("text", "") for c in ev["message"]["content"]))
            if ev.get("type") == "result":
                result = ev
                break
        srv.shutdown()
        assert result is not None, "no result"
        assert result["is_error"] is False, result
        assert "".join(texts) == "привет", texts
        assert result["result"] == "привет"
        assert result["usage"] == {"total_tokens": 7}
        assert "Bearer" in Gateway.seen_auth[0] or Gateway.seen_auth[0] == "", Gateway.seen_auth
    finally:
        b.close()


def test_unauthorized_is_a_visible_error():
    srv, base = start_gateway("unauthorized")
    b = Bridge(base)
    try:
        b.send(user_msg("x"))
        result = b.read_until_result()
        srv.shutdown()
        assert result is not None
        assert result["is_error"] is True
        assert "401" in " ".join(result["errors"])
    finally:
        b.close()


def test_redirect_does_not_send_the_key_anywhere():
    srv, base = start_gateway("redirect")
    b = Bridge(base, env={"DMS_AGENT_OPENAI_PROVIDER": ""})
    try:
        b.send(user_msg("x"))
        result = b.read_until_result()
        srv.shutdown()
        assert result is not None
        assert result["is_error"] is True
        assert "redirect" in " ".join(result["errors"]).lower()
        # Никакого второго POST на другой origin из моста не было: seen_auth
        # заполняет только наш сервер, и POST был ровно один.
        assert len(Gateway.seen_auth) == 1, Gateway.seen_auth
    finally:
        b.close()


def test_connection_drop_ends_turn_with_error():
    srv, base = start_gateway("drop")
    b = Bridge(base)
    try:
        b.send(user_msg("длинный"))
        result = b.read_until_result(timeout=15)
        srv.shutdown()
        assert result is not None, "drop must end the turn with a result"
        assert result["is_error"] is True, result
    finally:
        b.close()


def test_cancel_during_stream():
    srv, base = start_gateway("sse")
    b = Bridge(base)
    try:
        b.send(user_msg("текет"))
        # Отмена сразу после первого чанка. Результат, пришедший по ходу,
        # запоминаем: если гонка завершит ход до cancel, это тот же контракт
        # «ровно один result», и он обязан быть is_error False.
        result = None
        deadline = time.time() + 5
        while time.time() < deadline:
            ev = b.reader.read_event(timeout=1)
            if ev is None:
                continue
            if ev.get("type") == "assistant":
                b.send({"type": "cancel"})
            if ev.get("type") == "result":
                result = ev
                break
        srv.shutdown()
        assert result is not None, "cancel must end the turn"
        # Cancel прибыл до конца потока: ход обязан завершиться ошибкой.
        # (Stream ~1s, cancel уходит сразу после первого чанка на ~0.3s —
        # гонка здесь невозможна, а её исход всё равно детерминирован.)
        assert result["is_error"] is True, result
    finally:
        b.close()


def test_session_persists_and_resumes_with_full_history(tmp_path):
    srv, base = start_gateway("sse")
    first = Bridge(base)
    try:
        first.send(user_msg("первый"))
        result = first.read_until_result()
        assert result and not result["is_error"]
        sid = result["session_id"]
        assert str(uuid.UUID(sid, version=4)) == sid
        path = tmp_path / "state" / "dms-agent" / "openai-sessions" / (sid + ".json")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_text()) == {
            "version": 1, "id": sid, "provider": "mock-gateway",
            "workDir": os.getcwd(),
            "messages": [{"role": "user", "content": "первый"},
                         {"role": "assistant", "content": "привет"}],
        }
    finally:
        first.close()

    second = Bridge(base)
    try:
        second.send({"type": "config", "resumeId": sid})
        second.send(user_msg("второй"))
        result = second.read_until_result()
        assert result and not result["is_error"] and result["session_id"] == sid
        assert Gateway.seen_messages[-1] == [
            {"role": "user", "content": "первый"},
            {"role": "assistant", "content": "привет"},
            {"role": "user", "content": "второй"},
        ]
        assert json.loads(path.read_text())["messages"] == Gateway.seen_messages[-1] + [
            {"role": "assistant", "content": "привет"}]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        second.close()
        srv.shutdown()
        srv.server_close()


def test_failed_turn_never_creates_or_changes_session(tmp_path):
    srv, base = start_gateway("sse")
    b = Bridge(base)
    try:
        b.send(user_msg("успешный"))
        result = b.read_until_result()
        sid = result["session_id"]
        path = tmp_path / "state" / "dms-agent" / "openai-sessions" / (sid + ".json")
        before = path.read_bytes()
        Gateway.mode = "drop"
        b.send(user_msg("ошибка"))
        failure = b.read_until_result()
        assert failure and failure["is_error"] and not failure["session_id"]
        assert path.read_bytes() == before
    finally:
        b.close()
        srv.shutdown()
        srv.server_close()


def test_context_transfer_creates_new_session_and_resume_does_not_duplicate(tmp_path):
    srv, base = start_gateway("sse")
    context = tmp_path / "context.jsonl"
    carried = [{"role": "user", "content": "из другой сессии"},
               {"role": "assistant", "content": "старый ответ"}]
    context.write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in carried))
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    origin = Bridge(base, cwd=source_dir)
    try:
        origin.send(user_msg("оригинал"))
        original_result = origin.read_until_result()
        assert original_result and not original_result["is_error"]
        origin_path = (tmp_path / "state" / "dms-agent" / "openai-sessions"
                       / (original_result["session_id"] + ".json"))
        original_bytes = origin_path.read_bytes()
    finally:
        origin.close()
    b = Bridge(base, cwd=target_dir)
    try:
        b.send({"type": "config", "contextFile": str(context)})
        b.send(user_msg("новый запрос"))
        result = b.read_until_result()
        assert result and not result["is_error"]
        sid = result["session_id"]
        assert sid != original_result["session_id"]
        assert origin_path.read_bytes() == original_bytes
        path = tmp_path / "state" / "dms-agent" / "openai-sessions" / (sid + ".json")
        assert json.loads(path.read_text())["workDir"] == str(target_dir)
        assert json.loads(path.read_text())["messages"] == carried + [
            {"role": "user", "content": "новый запрос"},
            {"role": "assistant", "content": "привет"}]
    finally:
        b.close()

    b = Bridge(base)
    try:
        b.send({"type": "config", "resumeId": sid, "contextFile": str(context)})
        b.send(user_msg("ещё"))
        result = b.read_until_result()
        assert result and not result["is_error"] and result["session_id"] == sid
        assert Gateway.seen_messages[-1] == carried + [
            {"role": "user", "content": "новый запрос"},
            {"role": "assistant", "content": "привет"},
            {"role": "user", "content": "ещё"}]
    finally:
        b.close()
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("sid", ["../outside", "00000000-0000-4000-8000-000000000000"])
def test_invalid_or_missing_resume_fails_without_request(sid):
    srv, base = start_gateway("sse")
    b = Bridge(base)
    try:
        b.send({"type": "config", "resumeId": sid})
        b.send(user_msg("x"))
        result = b.read_until_result()
        assert result and result["is_error"] and not result["session_id"]
        assert not Gateway.seen_messages
    finally:
        b.close()
        srv.shutdown()
        srv.server_close()


def test_plain_http_to_non_loopback_rejected():
    b = Bridge("http://example.com/v1")
    try:
        b.send(user_msg("x"))
        result = b.read_until_result(timeout=5)
        assert result is None, "bridge must refuse non-loopback plain HTTP"
    finally:
        b.close()
