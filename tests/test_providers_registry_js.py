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
