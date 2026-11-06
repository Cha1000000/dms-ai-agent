"""TDD: мост ACP -> канонический stream-json (шаг 3 плана dms-glittery-sketch).

Контракт моста bridges/acp_bridge.py:
  - argv: <command...> (агент, запускается напрямую, без shell), env наследуется;
  - stdin моста: строки JSON — {type:"user", message:{role:"user",content:...}}
    (каноническое user-сообщение), {type:"control_response",response:{...}}
    (ответ на permission), {type:"control_request",... нет — cancel приходит
    как {"type":"cancel"}>;
  - stdout моста: канонические события claude stream-json: assistant/result;
    result обязан прийти РОВНО один раз на ход, с session_id;
  - initialize -> session/new (или load при resumeId) -> set_config_option
    (model/effort по реальным option id) -> prompt;
  - session/request_permission -> канонический control_request (can_use_tool)
    c request_id = JSON-RPC id; ответ allow -> optionId выбранного варианта
    (kind allow_once/allow_always), deny -> reject; response.missingOption
    запрещён — если вариант не найден среди предложенных, мост отвечает
    cancelled и завершает ход с ошибкой;
  - session/cancel при отмене: pending permission-запросы получают outcome
    cancelled, ход завершается result-ом с is_error=true (stop cancelled);
  - EOF/невалидный JSON/обрыв: result с is_error, session_id не выдумывается.
"""
import json
import os
import select
import subprocess
import sys
import time

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from bridge_test_utils import LineReader, read_event
BRIDGE = os.environ.get("ACP_TEST_BRIDGE", os.path.join(PLUGIN, "bridges", "acp_bridge.py"))
MOCK = os.path.join(PLUGIN, "tests", "mock_acp_agent.py")


class Bridge:
    def __init__(self, agent_args, cwd=None, agent=MOCK):
        self.proc = subprocess.Popen(
            [sys.executable, BRIDGE, sys.executable, agent, *agent_args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=cwd, bufsize=1,
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


def test_happy_path_turn():
    b = Bridge([])
    try:
        b.send(user_msg("привет"))
        result = b.read_until_result()
        assert result is not None, "no result event"
        assert result["session_id"] == "sess-123"
        assert result["is_error"] is False
        # Полный текст ассистента собран из чанков.
        texts = [ev for ev in b.lines if ev.get("type") == "assistant"]
        assert texts, "no assistant event"
        content = texts[0]["message"]["content"]
        assert any(c.get("type") == "text" and "echo:привет" in c.get("text", "") for c in content)
    finally:
        b.close()


def test_model_and_effort_applied_by_real_option_id():
    b = Bridge(["legacy"], agent=os.path.join(PLUGIN, "tests", "test_acp_contract.py"))
    try:
        b.send({"type": "config", "model": "m-big", "effort": "e-low"})
        b.send(user_msg("x"))
        result = b.read_until_result()
        assert result is not None
        assert result["is_error"] is False, result.get("result", "")
    finally:
        b.close()


def test_resume_uses_session_load():
    b = Bridge(["--expect-load"])
    try:
        b.send({"type": "config", "resumeId": "sess-123"})
        b.send(user_msg("продолжаем"))
        result = b.read_until_result()
        assert result is not None and result["is_error"] is False
    finally:
        b.close()


def test_permission_roundtrip():
    b = Bridge(["--ask"])
    try:
        b.send(user_msg("сделай"))
        req = None
        while True:
            ev = read_event(b.reader, timeout=10)
            if ev is None:
                break
            if ev.get("type") == "control_request":
                req = ev
                break
        assert req is not None, "bridge never asked for permission"
        assert req["request_id"]
        tool_call = req["request"]["tool_call"]
        assert tool_call
        # Отвечаем разрешением — мост должен выбрать РЕАЛЬНЫЙ optionId.
        b.send({"type": "control_response", "response": {
            "subtype": "success", "request_id": req["request_id"],
            "response": {"behavior": "allow"}}})
        result = b.read_until_result()
        assert result is not None, "no result after allow"
        assert result["is_error"] is False, result
    finally:
        b.close()


def test_permission_deny():
    b = Bridge(["--ask"])
    try:
        b.send(user_msg("сделай"))
        ev = None
        while True:
            e = read_event(b.reader, timeout=10)
            if e is None:
                break
            if e.get("type") == "control_request":
                ev = e
                break
        assert ev is not None, "bridge never asked for permission"
        b.send({"type": "control_response", "response": {
            "subtype": "success", "request_id": ev["request_id"],
            "response": {"behavior": "deny", "message": "нет"}}})
        result = b.read_until_result()
        assert result is not None
        # Отказ доведён до агента; ход завершается штатно или ошибкой — но
        # НЕ зависает и не молчит.
        assert result.get("is_error") is not None
    finally:
        b.close()


def test_cancel_terminates_turn():
    # --ask parks the turn on the permission dialog — a stable point where
    # the turn is genuinely in flight (the plain mock answers instantly and
    # the cancel would race its result).
    b = Bridge(["--ask"])
    try:
        b.send(user_msg("долго"))
        req = None
        while True:
            ev = read_event(b.reader, timeout=10)
            if ev is None:
                break
            if ev.get("type") == "control_request":
                req = ev
                break
        assert req is not None, "bridge never asked for permission"
        b.send({"type": "cancel"})
        result = b.read_until_result()
        assert result is not None, "cancel must end the turn with a result"
        assert result["is_error"] is True, result
    finally:
        b.close()


def test_broken_stdin_json_does_not_crash_bridge():
    b = Bridge([])
    try:
        b.proc.stdin.write("это не json\n")
        b.proc.stdin.flush()
        b.send(user_msg("ок"))
        result = b.read_until_result()
        assert result is not None
        assert result["is_error"] is False
    finally:
        b.close()


def test_model_selected_through_the_models_shape():
    """The second ACP config shape (gemini-cli 0.66): the model list comes as
    models.availableModels and the selection is session/set_model. The bridge
    has to speak it — otherwise every turn fails with "option unavailable"."""
    b = Bridge(["models-form"])
    try:
        b.send({"type": "config", "model": "m-big"})
        b.send(user_msg("привет"))
        result = b.read_until_result()
        assert result is not None, "no result event"
        assert result["is_error"] is False, result.get("errors")
    finally:
        b.close()


def test_models_shape_rejects_a_model_the_agent_did_not_offer():
    b = Bridge(["models-form"])
    try:
        b.send({"type": "config", "model": "m-nope"})
        b.send(user_msg("привет"))
        result = b.read_until_result()
        assert result is not None
        assert result["is_error"] is True, result
        assert any("not offered" in e for e in result["errors"]), result
    finally:
        b.close()


def test_initialize_sends_valid_client_capabilities():
    """The client capabilities must be an object, and `fs` inside it — a
    boolean there is rejected by real agents (gemini --acp answers
    "expected 'object', received boolean"). The mock agent enforces the same
    schema, so a broken bridge fails this test."""
    b = Bridge([])
    try:
        b.send(user_msg("привет"))
        result = b.read_until_result()
        assert result is not None, "no result event"
        assert result["is_error"] is False, result.get("errors")
    finally:
        b.close()
