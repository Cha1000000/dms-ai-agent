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
    reg.set_provider("a", {"title": "A", "adapter": "openai"})
    reg.set_key("cvc", "sk-test")
    reg.set_provider("b", {"title": "B", "adapter": "openai"})
    data = reg.load()
    assert set(data["providers"]) == {"a", "b"}
    assert data["keys"]["cvc"]["apiKey"] == "sk-test"


def test_remove_provider_keeps_keys(store):
    reg.set_provider("a", {"title": "A", "adapter": "openai"})
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
    reg.set_provider("a", {"title": "A", "adapter": "openai"})
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
    reg.set_provider("codex", {"title": "Codex", "adapter": "codex"})
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
        reg.set_provider("a", {"title": "A", "adapter": "openai"})
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
        reg.set_provider("Bad/Id", {"title": "X", "adapter": "openai"})
    with pytest.raises(reg.ValidationError):
        reg.set_provider("..", {"title": "X", "adapter": "openai"})


def test_rejects_unknown_adapter(store):
    with pytest.raises(reg.ValidationError):
        reg.set_provider("x", {"title": "X", "adapter": "brainfuck"})


def test_rejects_non_dict_entry(store):
    with pytest.raises(reg.ValidationError):
        reg.set_provider("x", "строка вместо объекта")


# --- конкурентность ---------------------------------------------------------


def test_concurrent_writes_do_not_lose_updates(store):
    """Два потока пишут по разным провайдерам — обе записи должны дожить."""
    errors = []

    def worker(name):
        try:
            for i in range(15):
                reg.set_provider(f"{name}-{i}", {"title": name, "adapter": "openai"})
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
    reg.set_provider("codex", {"title": "Codex", "adapter": "codex"})
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
