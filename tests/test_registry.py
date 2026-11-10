"""TDD: провайдерный реестр $XDG_STATE_HOME/dms-agent/providers.json.

Контракт (plans/dms-glittery-sketch.md, раздел «Реестр, секреты и граница доверия»):
  файл один, секции providers + keys, режим 0600.
  - одна точка правды о пути: registry.path() учитывает XDG_STATE_HOME и
    PROVIDER_REGISTRY (тестовый override) — тот же путь, что и у provider_secrets;
  - миграция старого плоского {"cvc":{"apiKey":...}} происходит при чтении:
    ключ перекладывается в keys, providers остаётся пустым, файл не перезаписан
    до первой записи;
  - новая запись всегда в формате {"version":1,"providers":{},"keys":{}};
  - повреждённый JSON/неизвестная версия -> ошибка чтения, НИКОГДА не перезапись
    исходника пустым реестром;
  - атомарная запись 0600 под flock: конкурентные обновления не теряются;
  - валидация: id по ^[a-z0-9-]+$, adapter из известного набора, иначе ошибка.
"""
import json
import os
import stat
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import registry as reg  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Чистый реестр во временном XDG_STATE_HOME."""
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.delenv("PROVIDER_REGISTRY", raising=False)
    monkeypatch.setattr(reg, "REGISTRY_PATH", reg._registry_path())
    return reg


def test_path_honours_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.delenv("PROVIDER_REGISTRY", raising=False)
    p = reg._registry_path()
    assert p == str(tmp_path / "st" / "dms-agent" / "providers.json")


def test_path_override_wins_over_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("PROVIDER_REGISTRY", str(tmp_path / "custom.json"))
    assert reg._registry_path() == str(tmp_path / "custom.json")


def test_default_path_uses_home_expansion(monkeypatch):
    monkeypatch.delenv("PROVIDER_REGISTRY", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", "~/.local/state")
    p = reg._registry_path()
    assert "~" not in p
    assert p.endswith(".local/state/dms-agent/providers.json")


def test_empty_store_gives_empty_sections(store):
    data = reg.load()
    assert data == {"version": 1, "providers": {}, "keys": {}}


def test_set_provider_roundtrip(store):
    entry = {"title": "Мой шлюз", "adapter": "openai", "baseUrl": "https://x.example/v1"}
    reg.set_provider("my-gateway", entry)
    data = reg.load()
    assert data["providers"]["my-gateway"] == entry


def test_set_provider_keeps_others_and_keys(store):
    reg.set_provider("a", {"title": "A", "adapter": "openai", "baseUrl": "https://a.example/v1"})
    reg.set_key("cvc", "sk-test")
    reg.set_provider("b", {"title": "B", "adapter": "openai", "baseUrl": "https://b.example/v1"})
    data = reg.load()
    assert set(data["providers"]) == {"a", "b"}
    assert data["keys"]["cvc"]["apiKey"] == "sk-test"


def test_remove_provider_keeps_keys(store):
    reg.set_provider("a", {"title": "A", "adapter": "openai", "baseUrl": "https://a.example/v1"})
    reg.set_key("cvc", "sk-test")
    assert reg.remove_provider("a") is True
    data = reg.load()
    assert data["providers"] == {}
    assert data["keys"]["cvc"]["apiKey"] == "sk-test"


def test_key_roundtrip_and_removal(store):
    reg.set_key("gw", "sk-1")
    assert reg.get_key("gw") == "sk-1"
    reg.set_key("gw", "")  # пустая строка — явное «забыть»
    assert reg.get_key("gw") == ""
    assert reg.load()["keys"] == {}


def test_file_mode_is_0600(store):
    reg.set_provider("a", {"title": "A", "adapter": "openai", "baseUrl": "https://a.example/v1"})
    mode = stat.S_IMODE(os.stat(store.REGISTRY_PATH).st_mode)
    assert mode == 0o600
    # Лок-файл тоже не должен быть читаем всем.
    lock = store.REGISTRY_PATH + ".lock"
    assert stat.S_IMODE(os.stat(lock).st_mode) == 0o600


# --- миграция старого плоского формата -------------------------------------


def test_flat_legacy_file_migrates_on_read(store):
    os.makedirs(os.path.dirname(store.REGISTRY_PATH), exist_ok=True)
    with open(store.REGISTRY_PATH, "w") as fh:
        json.dump({"cvc": {"apiKey": "sk-real"}}, fh)
    data = reg.load()
    assert data["keys"]["cvc"]["apiKey"] == "sk-real"
    assert data["providers"] == {}
    assert data["version"] == 1


def test_migration_does_not_rewrite_until_a_write(store):
    """Чтение не должно перезаписывать файл: вдруг его пишет параллельный процесс."""
    os.makedirs(os.path.dirname(store.REGISTRY_PATH), exist_ok=True)
    with open(store.REGISTRY_PATH, "w") as fh:
        json.dump({"cvc": {"apiKey": "sk-real"}}, fh)
    before = open(store.REGISTRY_PATH).read()
    reg.load()
    assert open(store.REGISTRY_PATH).read() == before


def test_migration_survives_a_write(store):
    """После миграции ключ жив и запись настроек его не теряет."""
    os.makedirs(os.path.dirname(store.REGISTRY_PATH), exist_ok=True)
    with open(store.REGISTRY_PATH, "w") as fh:
        json.dump({"cvc": {"apiKey": "sk-real"}}, fh)
    reg.set_provider("codex", {"title": "Codex", "adapter": "codex", "command": ["codex", "exec", "--json"]})
    data = reg.load()
    assert data["keys"]["cvc"]["apiKey"] == "sk-real"
    assert data["providers"]["codex"]["adapter"] == "codex"


def test_provider_secrets_reads_migrated_key(store, tmp_path, monkeypatch):
    """provider_secrets через общий модуль видит ключ из старого плоского файла."""
    import provider_secrets as ps
    os.makedirs(os.path.dirname(store.REGISTRY_PATH), exist_ok=True)
    with open(store.REGISTRY_PATH, "w") as fh:
        json.dump({"cvc": {"apiKey": "sk-real"}}, fh)
    assert ps.get_api_key("cvc") == "sk-real"


# --- повреждённые данные: ошибка, но не перезапись --------------------------


def test_corrupt_file_raises_and_is_not_rewritten(store):
    os.makedirs(os.path.dirname(store.REGISTRY_PATH), exist_ok=True)
    with open(store.REGISTRY_PATH, "w") as fh:
        fh.write("{not json")
    with pytest.raises(reg.RegistryError):
        reg.load()
    # После попытки записи исходник тоже не затёрт.
    with pytest.raises(reg.RegistryError):
        reg.set_provider("a", {"title": "A", "adapter": "openai", "baseUrl": "https://a.example/v1"})
    assert open(store.REGISTRY_PATH).read() == "{not json"


def test_unknown_version_raises(store):
    os.makedirs(os.path.dirname(store.REGISTRY_PATH), exist_ok=True)
    with open(store.REGISTRY_PATH, "w") as fh:
        json.dump({"version": 99, "providers": {}, "keys": {}}, fh)
    with pytest.raises(reg.RegistryError):
        reg.load()


# --- валидация --------------------------------------------------------------


def test_rejects_bad_provider_id(store):
    with pytest.raises(reg.ValidationError):
        reg.set_provider("Bad/Id", {"title": "X", "adapter": "openai", "baseUrl": "https://x.example/v1"})
    with pytest.raises(reg.ValidationError):
        reg.set_provider("..", {"title": "X", "adapter": "openai", "baseUrl": "https://x.example/v1"})


def test_rejects_unknown_adapter(store):
    with pytest.raises(reg.ValidationError):
        reg.set_provider("x", {"title": "X", "adapter": "brainfuck"})


def test_rejects_non_dict_entry(store):
    with pytest.raises(reg.ValidationError):
        reg.set_provider("x", "строка вместо объекта")


def test_rejects_builtin_provider_ids(store):
    """A registry entry must never shadow a built-in provider (chat, catalogs
    and history are keyed on the id)."""
    for pid in ("claude", "cvc", "qoder", "kimi"):
        with pytest.raises(reg.ValidationError):
            reg.set_provider(pid, {"adapter": "openai", "baseUrl": "https://x.example/v1"})
        with pytest.raises(reg.ValidationError):
            reg.set_provider(pid, {"adapter": "acp", "command": ["/bin/true"]})


def test_accepts_a_claude_protocol_cli(store):
    """A CLI that speaks the Claude Code stream-json protocol is a first-class
    registry provider: the command may carry its own env prefix."""
    reg.set_provider("wrap", {"adapter": "claude-cli",
                              "command": ["env", "X=1", "wrap-cli"]})
    assert reg.load()["providers"]["wrap"]["adapter"] == "claude-cli"


def test_rejects_a_key_or_unknown_field_in_a_provider_entry(store):
    with pytest.raises(reg.ValidationError):
        reg.set_provider("gw", {"adapter": "openai", "baseUrl": "https://x.example/v1",
                                "apiKey": "sk-should-not-be-here"})
    with pytest.raises(reg.ValidationError):
        reg.set_provider("gw", {"adapter": "openai", "baseUrl": "https://x.example/v1",
                                "env": {"A": "B"}})


def test_rejects_http_for_a_remote_gateway(store):
    with pytest.raises(reg.ValidationError):
        reg.set_provider("gw", {"adapter": "openai", "baseUrl": "http://example.org/v1"})
    # Loopback HTTP stays allowed (a local gateway).
    reg.set_provider("local", {"adapter": "openai", "baseUrl": "http://127.0.0.1:8080/v1"})


def test_requires_a_real_command_for_agent_adapters(store):
    for entry in ({"adapter": "acp"},
                  {"adapter": "acp", "command": ""},
                  {"adapter": "acp", "command": "gemini --experimental-acp"},
                  {"adapter": "codex", "command": ["codex", 4]}):
        with pytest.raises(reg.ValidationError):
            reg.set_provider("x", entry)


def test_gateway_url_is_normalized(store):
    reg.set_provider("gw", {"adapter": "openai", "baseUrl": "https://x.example/v1/"})
    assert reg.load()["providers"]["gw"]["baseUrl"] == "https://x.example/v1"


def test_remove_provider_drops_its_key(store):
    reg.set_provider("gw", {"adapter": "openai", "baseUrl": "https://x.example/v1"})
    reg.set_key("gw", "sk-secret")
    assert reg.remove_provider("gw") is True
    assert "gw" not in reg.load()["keys"]


# --- конкурентность ---------------------------------------------------------


def test_concurrent_writes_do_not_lose_updates(store):
    """Два потока пишут по разным провайдерам — обе записи должны дожить."""
    errors = []

    def worker(name):
        try:
            for i in range(15):
                reg.set_provider(f"{name}-{i}", {"title": name, "adapter": "openai",
                                                 "baseUrl": "https://gw.example/v1"})
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    data = reg.load()
    assert len(data["providers"]) == 30


def test_cli_list_json(store):
    """CLI-контракт: `registry.py list --json` отдаёт машинный JSON для QML."""
    reg.set_provider("codex", {"title": "Codex", "adapter": "codex", "command": ["codex", "exec", "--json"]})
    reg.set_key("cvc", "sk-real")
    out = subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "registry.py"), "list", "--json"],
        capture_output=True, text=True, check=True,
        env=dict(os.environ, XDG_STATE_HOME=os.path.dirname(os.path.dirname(store.REGISTRY_PATH))),
    )
    data = json.loads(out.stdout)
    assert data["providers"]["codex"]["adapter"] == "codex"
    # Ключи не едут в list --json для QML: UI их не показывает.
    assert "keys" not in data


PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
