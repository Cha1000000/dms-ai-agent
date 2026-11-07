"""TDD: подключаемые провайдеры в providers.js (шаг 2 плана dms-glittery-sketch).

Контракт:
  - setRegistry(data) добавляет провайдеров из providers.json к встроенным;
    адаптер acp/codex/openai становится дескриптором с id/title/adapter из
    реестра;
  - byId находит и встроенного, и реестрового; НЕИЗВЕСТНЫЙ id возвращает
    undefined — чат не должен молча подменять провайдера на claude;
  - registryAll() = встроенные + реестровые (реестровые после встроенных);
  - descriptor реестрового провайдера помечен adapter (тип моста) и command,
    где адаптеру нужна команда;
  - повторный setRegistry ЗАМЕНЯЕТ предыдущий набор реестровых, а встроенные
    не дублируются и не затираются;
  - битые записи реестра (не object / без id) пропускаются, не роняя всё.
"""
import json
import os
import subprocess

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(os.path.dirname(__file__), "run_provider.js")

run = lambda fn, arg: json.loads(subprocess.run(
    ["node", NODE, fn, json.dumps(arg)], capture_output=True, text=True, check=True,
    cwd=PLUGIN,
).stdout)


def _registry(providers):
    return {"version": 1, "providers": providers, "keys": {}}


def test_set_registry_adds_a_provider():
    out = run("registry_set", {"data": _registry({
        "my-gw": {"title": "Мой шлюз", "adapter": "openai", "baseUrl": "https://x/v1"},
    })})
    p = out["byId"]["my-gw"]
    assert p["title"] == "Мой шлюз"
    assert p["adapter"] == "openai"
    assert p["baseUrl"] == "https://x/v1"
    # Встроенные остались на месте.
    assert out["byId"]["claude"]["id"] == "claude"
    # Неизвестный id — undefined, а не claude.
    assert out["unknownId"] is None
    assert "claude" in out["allIds"] and "my-gw" in out["allIds"]


def test_second_set_replaces_but_keeps_builtin():
    run("registry_set", {"data": _registry({"a": {"title": "A", "adapter": "acp"}})})
    out = run("registry_set", {"data": _registry({
        "b": {"title": "B", "adapter": "codex", "command": "codex exec --json"},
    })})
    assert set(out["allIds"]) >= {"claude", "b"}
    assert "a" not in out["allIds"]


def test_bridge_events_are_forwarded_to_the_chat():
    data = _registry({"gateway": {"adapter": "openai", "baseUrl": "https://x/v1"}})
    event = {"type": "result", "result": "Полный ответ", "is_error": False}
    assert run("registry_parse", {"data": data, "id": "gateway", "line": json.dumps(event)}) == [event]
    assert run("registry_parse", {"data": data, "id": "gateway", "line": "not json"}) == []


def test_gateway_command_passes_provider_identity_without_a_key():
    data = _registry({"gateway": {"adapter": "openai", "baseUrl": "https://x/v1"}})
    command = run("registry_command", {"data": data, "id": "gateway"})["cmd"]
    assert "DMS_AGENT_OPENAI_PROVIDER='gateway'" in command
    assert "https://x/v1" in command


def test_bad_entries_are_skipped():
    out = run("registry_set", {"data": _registry({
        "good": {"title": "G", "adapter": "acp"},
        "bad": "не объект",
        "noadapter": {"title": "N"},
        "Bad/Id": {"title": "X", "adapter": "acp"},
    })})
    assert "good" in out["allIds"]
    # Не-объект и запись без adapter пропущены, весь набор не упал.
    assert "bad" not in out["allIds"]
    assert "noadapter" not in out["allIds"]
    # id, невалидный по правилу реестра (registry.py), тоже не проходит.
    assert "Bad/Id" not in out["allIds"]


def test_a_registry_entry_cannot_shadow_a_builtin_provider():
    out = run("registry_set", {"data": _registry({
        "cvc": {"title": "Fake CVC", "adapter": "acp", "command": ["x"]},
    })})
    # The built-in descriptor is untouched and there is no duplicate id.
    assert out["byId"]["cvc"]["title"] == "CheapVibeCode"
    assert out["byId"]["cvc"]["adapter"] is None
    assert out["allIds"].count("cvc") == 1


def test_cancel_speaks_each_provider_protocol():
    # The claude CLI and its gateways stop on control_request/interrupt.
    claude = run("cancelMessage", {"id": "claude", "requestId": 9})
    assert claude == {"type": "control_request", "request_id": "cancel_9",
                      "request": {"subtype": "interrupt", "cancel_queued": True}}
    cvc = run("cancelMessage", {"id": "cvc", "requestId": 9})
    assert cvc["type"] == "control_request"
    # A bridge provider reads its own small line; the claude interrupt was
    # ignored by all three bridges (Stop fell through to SIGTERM).
    data = _registry({"gw": {"adapter": "openai", "baseUrl": "https://x/v1"}})
    gw = run("cancelMessage", {"data": data, "id": "gw", "requestId": 9})
    assert gw == {"type": "cancel"}


def test_sign_in_hints_name_the_adapter():
    assert run("hintKey", {"id": "cvc"}) == "loginHint.cvc"
    assert run("hintKey", {"id": "cc9"}) == "loginHint.cc9"
    data = _registry({
        "gw": {"adapter": "openai", "baseUrl": "https://x/v1"},
        "cx": {"adapter": "codex", "command": ["codex", "exec", "--json"]},
        "acp": {"adapter": "acp", "command": ["agent", "--acp"]},
    })
    assert run("hintKey", {"data": data, "id": "gw"}) == "loginHint.gateway"
    assert run("hintKey", {"data": data, "id": "cx"}) == "loginHint.codex"
    assert run("hintKey", {"data": data, "id": "acp"}) == "loginHint.generic"
    assert run("hintKey", {"id": "no-such-provider"}) == "loginHint.generic"


def test_live_checks_are_not_cached_by_the_chat():
    # cc9 readiness is a running gateway, cvc's is a stored key that can be
    # deleted mid-session: neither may be cached for the shell's lifetime.
    assert run("descriptor_flag", {"id": "cc9", "flag": "liveSignIn"}) is True
    assert run("descriptor_flag", {"id": "cvc", "flag": "liveSignIn"}) is True
    for pid in ("claude", "qoder", "kimi"):
        assert run("descriptor_flag", {"id": pid, "flag": "liveSignIn"}) is False
