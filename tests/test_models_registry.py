"""TDD: каталог моделей реестровых провайдеров (шаг 3 плана).

Контракт models.py:
  - провайдер из providers.json (adapter acp/codex/openai) принимается вместо
    неизвестной ошибки; модели берутся по adapter:
      * codex: `codex debug models` (JSON-строки; visibility "list" — видимые,
        "hide" — скрытые); per-model efforts из поля "efforts"/"supportedEfforts";
      * openai: GET {baseUrl}/models (Bearer-ключ из реестра), data[].id;
      * acp: command не даёт каталога сам — пустой список (наследуется от агента
        позже, шаг 4), НЕ фолбэк на claude;
  - для ВСЕХ каталогов действует фильтр: Combo-пресеты и токенаторные
    пространства имён не попадают в picker, id "default" — тоже;
  - у codex-каталога модель с visibility "hide" не показывается;
  - фильтр claude/fable применим к тем же полям, что и раньше;
  - неизвестный адаптер реестра — ошибка, не пустой список.
"""
import json
import os
import sys

import pytest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN)

import models  # noqa: E402
import registry as prov_registry  # noqa: E402


@pytest.fixture
def registry_state(tmp_path, monkeypatch):
    """Изолированный providers.json: my-acp (acp) и my-codex (codex)."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setattr(prov_registry, "REGISTRY_PATH", prov_registry._registry_path())
    prov_registry.set_provider("my-acp", {"adapter": "acp", "command": ["/bin/true"]})
    prov_registry.set_provider("my-codex", {"adapter": "codex", "command": ["codex"]})
    monkeypatch.setattr(models, "_registered", prov_registry.load().get("providers", {}))
    monkeypatch.setattr(models, "_registered_adapters",
                        {p: e.get("adapter") for p, e in models._registered.items()})
    return state


def codex_row(mid, visibility="list", efforts=None):
    # Реальный формат `codex debug models` (codex-cli 0.166.0): один JSON
    # {"models":[...]}, поля slug/display_name/visibility, efforts в
    # supported_reasoning_levels[].effort.
    return {"slug": mid, "display_name": mid.upper(), "visibility": visibility,
            "supported_reasoning_levels": [{"effort": e} for e in (efforts or [])]}


def test_codex_mapper_filters_hidden_and_applies_common_filters():
    rows = [
        codex_row("gpt-5.5"),
        codex_row("gpt-5.5-ultra", visibility="hide"),
        codex_row("tk/gpt-free"),          # tokenator namespace
        codex_row("claude-cowork-combo"),  # combo preset
        codex_row("default"),              # alias of another entry
        codex_row("claude-fable-x"),       # fable
        codex_row("luna", efforts=["low", "max"]),
    ]
    out = models.map_codex_models(rows)
    ids = [m["id"] for m in out]
    assert ids == ["gpt-5.5", "luna"], ids
    luna = out[1]
    assert luna["efforts"] == ["low", "max"]
    assert luna["label"] == "LUNA"


def test_codex_parser_reads_single_json_object():
    # codex-cli 0.166.0 печатает ОДИН JSON-объект {"models": [...]}, не строки.
    text = json.dumps({"models": [codex_row("gpt-5.5"), codex_row("secret", visibility="hide")]})
    out = models.map_codex_models(models.parse_codex_debug(text))
    assert [m["id"] for m in out] == ["gpt-5.5"]


def test_openai_mapper_reads_data_list():
    payload = {"data": [{"id": "gpt-x", "owned_by": "vendor"}]}
    out = models.map_openai_models(payload, "https://gw.example/v1")
    assert out[0]["id"] == "gpt-x"
    assert out[0]["resolved"] == "gpt-x"
    assert out[0]["efforts"] == []


def test_acp_registry_provider_has_no_catalog_yet(registry_state):
    # The ACP catalog comes from the agent's own session/new answer, so a
    # provider whose command is /bin/true has no catalog — but the failure
    # must be visible, not an empty list silently.
    with pytest.raises(RuntimeError):
        models.fetch_models_for("my-acp")


def test_all_catalogs_filter_combo_and_tokenator():
    rows = [{"slug": "tk/paid", "visibility": "list", "supported_reasoning_levels": []},
            {"slug": "claude-cowork-combo", "visibility": "list", "supported_reasoning_levels": []}]
    assert models.map_codex_models(rows) == []
    payload = {"data": [{"id": "tk/paid"}, {"id": "free-models"}]}
    assert models.map_openai_models(payload, "https://x/v1") == []


def test_acp_mapper_reads_models_form():
    # gemini-cli 0.66 sends models.availableModels, not configOptions.
    result = {"models": {"availableModels": [
        {"modelId": "gemini-3.5-flash-lite", "name": "Flash Lite"},
        {"modelId": "auto", "name": "Auto"},
    ], "currentModelId": "auto"}}
    out = models.map_acp_models(result)
    assert [m["id"] for m in out] == ["gemini-3.5-flash-lite", "auto"]
    assert out[0]["label"] == "Flash Lite"
    assert out[0]["resolved"] == "gemini-3.5-flash-lite"
    assert out[0]["efforts"] == []


def test_acp_mapper_reads_config_options_form():
    result = {"configOptions": [
        {"id": "model", "category": "model", "type": "select",
         "options": [{"value": "m-fast", "name": "Fast"}, {"value": "m-big"}]},
        {"id": "effort", "category": "effort", "type": "select",
         "options": [{"value": "low"}]},
    ]}
    out = models.map_acp_models(result)
    assert [m["id"] for m in out] == ["m-fast", "m-big"]


def test_acp_mapper_filters_combo_and_tokenator():
    result = {"models": {"availableModels": [
        {"modelId": "tk/free"}, {"modelId": "free-models"},
        {"modelId": "claude-cowork-combo"}, {"modelId": "good-model"}]}}
    assert [m["id"] for m in models.map_acp_models(result)] == ["good-model"]


def test_combo_and_tokenator_are_filtered_inside_a_namespace():
    """The gateway namespaces the same presets ("9router/claude-cowork-combo",
    "9router/tk-free", "9router/tk/claude-opus-5"): the ban is on the preset,
    not on its spelling. "Никаких Комбо и моделей Токенатора в Джарвисе быть
    не должно"."""
    banned = ["9router/claude-cowork-combo", "9router/free-models",
              "9router/tk-free", "9router/tokenator-paid",
              "9router/tk/claude-opus-5", "tk/anything",
              "tokenator/claude-opus-5", "tokenator/free-gpt-6-astra"]
    kept = ["9router/kc/google/gemini-2.5-flash", "9router/kimi/kimi-k3",
            "9router/bzl/auto:free"]
    for mid in banned:
        assert not models.claude_model_id(mid), mid
    for mid in kept:
        assert models.claude_model_id(mid), mid


def test_unknown_registry_provider_still_rejected(registry_state, capsys):
    with pytest.raises(RuntimeError):
        models.fetch_models_for("brainfuck")
