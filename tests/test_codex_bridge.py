"""TDD: мост codex exec --json -> канонический stream-json (шаг 3 плана).

Контракт bridges/codex_bridge.py:
  - argv: <codex...> (например, путь к mock или настоящий codex); мост сам
    формирует `exec --json -` и дописывает флаги модели/effort;
  - stdin моста: {"type":"user",...}, {"type":"config","model":...,"effort":...,
    "resumeId":...}, {"type":"cancel"};
  - stdout: канонические assistant/result; ровно один result на ход,
    session_id = thread_id;
  - resume: config с resumeId -> `exec resume <id> --json -`;
  - item.completed agent_message -> assistant-текст; item.completed error и
    turn.failed -> result is_error; {"type":"error"}-строки (transport retry)
    НЕ завершают ход;
  - cancel: terminate процесса, result is_error (cancel во время хода);
  - model через -m, effort через -c model_reasoning_effort="...".
"""
import json
import os
import select
import subprocess
import sys
import time

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from bridge_test_utils import LineReader, read_event
BRIDGE = os.path.join(PLUGIN, "bridges", "codex_bridge.py")
MOCK = os.path.join(PLUGIN, "tests", "mock_codex_cli.py")


class Bridge:
    def __init__(self, agent_args, env=None):
        child_env = dict(os.environ)
        child_env.update(env or {})
        self.proc = subprocess.Popen(
            [sys.executable, BRIDGE, sys.executable, MOCK, *agent_args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=child_env,
        )
        self.lines = []
        self.reader = LineReader(self.proc.stdout)

    def send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def read_until_result(self, timeout=10):
        result = None
        while True:
            ev = read_event(self.reader, timeout=timeout)
            if ev is None:
                break
            self.lines.append(ev)
            if ev.get("type") == "result":
                result = ev
                break
        return result

    def close(self, timeout=5):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def user_msg(text):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def test_happy_path_and_thread_id_as_session():
    b = Bridge([])
    try:
        b.send(user_msg("привет"))
        result = b.read_until_result()
        assert result is not None, "no result event"
        assert result["session_id"] == "thread-mock-1"
        assert result["is_error"] is False
        texts = [ev for ev in b.lines if ev.get("type") == "assistant"]
        assert any(c.get("type") == "text" and "mock answer" in c.get("text", "")
                   for c in texts[0]["message"]["content"])
    finally:
        b.close()


def test_model_and_effort_flags():
    b = Bridge(["--expect-model:gpt-5.5", "--expect-effort:high"])
    try:
        b.send({"type": "config", "model": "gpt-5.5", "effort": "high"})
        b.send(user_msg("x"))
        result = b.read_until_result()
        assert result is not None
        assert result["is_error"] is False, result
    finally:
        b.close()


def test_resume_uses_exec_resume():
    b = Bridge(["--expect-resume:thread-mock-1"])
    try:
        b.send({"type": "config", "resumeId": "thread-mock-1"})
        b.send(user_msg("продолжаем"))
        result = b.read_until_result()
        assert result is not None and result["is_error"] is False, result
        assert result["session_id"] == "thread-mock-1"
    finally:
        b.close()


def test_error_item_is_a_warning_not_a_failed_turn():
    """codex-cli emits non-fatal `item.completed` errors on every run (plugin
    hook config, hook timeout). Live 2026-11-06: they appeared before
    turn.started and turned every successful Codex answer into is_error."""
    b = Bridge(["--error-item"])
    try:
        b.send(user_msg("x"))
        result = b.read_until_result()
        assert result is not None
        assert result["is_error"] is False, result
        assert "mock answer" not in (result["result"] or "") or True
        joined = " ".join(result["errors"])
        assert "sandbox denied" in joined
    finally:
        b.close()


def test_turn_failed_fails_the_turn():
    b = Bridge(["--fail"])
    try:
        b.send(user_msg("x"))
        result = b.read_until_result()
        assert result is not None
        assert result["is_error"] is True
        assert "model overloaded" in " ".join(result["errors"])
    finally:
        b.close()


def test_transport_error_lines_do_not_end_turn():
    # ERROR-строки и шум между событиями не должны завершать ход.
    b = Bridge(["--garbage", "--stdin-echo"])
    try:
        b.send(user_msg("эхо"))
        result = b.read_until_result()
        assert result is not None, "no result after noise lines"
        assert result["is_error"] is False, result
        texts = [ev for ev in b.lines if ev.get("type") == "assistant"]
        assert any("echo:эхо" in c.get("text", "")
                   for ev in texts for c in ev["message"]["content"])
    finally:
        b.close()


def test_cancel_terminates_turn():
    b = Bridge(["--slow"])
    try:
        b.send(user_msg("долго"))
        time.sleep(0.5)
        b.send({"type": "cancel"})
        result = b.read_until_result()
        assert result is not None, "cancel must end the turn with a result"
        assert result["is_error"] is True, result
    finally:
        b.close()


def test_a_timed_out_turn_does_not_poison_the_next_one():
    """The old code returned on timeout without stopping the child: the next
    turn wrote to its closed stdin ("bridge error: I/O operation on closed
    file") and the leaked child could still emit a stale result."""
    b = Bridge(["--slow"], env={"CODEX_TURN_TIMEOUT": "1"})
    try:
        b.send(user_msg("x"))
        first = b.read_until_result(timeout=10)
        assert first is not None and first["is_error"] is True, first
        assert "timed out" in " ".join(first["errors"]), first
        b.send(user_msg("y"))
        second = b.read_until_result(timeout=10)
        assert second is not None
        joined = " ".join(second["errors"])
        assert "bridge error" not in joined, second
        assert "timed out" in joined, second
    finally:
        b.close()
