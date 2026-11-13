"""TDD: mapping CheapVibeCode's /v1/models payload to the plugin's model list.

Contract (tools/plans/jarvis-multi-provider.md, этап 2):
  source GET https://ru.cheapvibecode.ru/v1/models (OpenAI-style {"data": [...]});
  output the same shape models.py prints for claude:
    [{"id", "label", "resolved", "desc", "efforts"}]
  - id/resolved are the full gateway id (the CLI always needs --model explicitly;
    their gateway rejects the bare "haiku"-style aliases).
  - label is display_name ("Claude Opus 5.5", "OpenAI · GPT 6.1 Sol").
  - efforts is the model's own supported_reasoning_levels (the "models" cards
    of the same payload) cut to the CLI enum; no card or no levels in it means
    no chip. Contract updated 13.11.2026 per the task "проверь актуальность
    списка моделей CVC ... и их уровни effort": a generic set per reasoning
    model offered levels the gateway silently drops (effort high logged as low).
  - broken entries (no id) are dropped, not fatal.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402


@pytest.fixture
def sample_payload():
    # Trimmed from a live GET /v1/models (01.11.2026), same field names.
    return {
        "object": "list",
        "data": [
            {
                "id": "claude-opus-5-5",
                "object": "model",
                "display_name": "Claude Opus 5.5",
                "series": "Claude Opus",
                "supports_reasoning": True,
                "supports_tools": True,
                "supports_vision": True,
                "input_modalities": ["text", "image"],
            },
            {
                "id": "claude-haiku-4-5",
                "display_name": "Claude Haiku 4.5",
                "supports_reasoning": None,
                "supports_tools": True,
                "supports_vision": True,
            },
            {
                "id": "gpt-6.1-sol",
                "display_name": "OpenAI · GPT 6.1 Sol",
                "supports_reasoning": True,
                "supports_vision": True,
            },
            {
                "id": "qwen3.8-max",
                "display_name": "Alibaba · Qwen3.8 Max",
                "supports_reasoning": True,
            },
            {
                "id": "minimax-m3.1-flash",
                "display_name": "MiniMax · MiniMax M3.1 Flash",
                "supports_reasoning": True,
            },
            {"id": "broken-no-display", "supports_reasoning": False},
            {"display_name": "orphan, no id"},
        ],
        # Catalog cards (top-level "models"), trimmed from the same live GET
        # (13.11.2026): slug + the real supported_reasoning_levels.
        "models": [
            {"slug": "claude-opus-5-5",
             "supported_reasoning_levels": [{"effort": e} for e in
                                            ("low", "medium", "high", "xhigh", "max")]},
            {"slug": "gpt-6.1-sol",
             "supported_reasoning_levels": [{"effort": e} for e in
                                            ("none", "low", "medium", "high", "xhigh", "max", "ultra")]},
            {"slug": "qwen3.8-max",
             "supported_reasoning_levels": [{"effort": e} for e in
                                            ("none", "low", "medium", "xhigh")]},
            {"slug": "minimax-m3.1-flash",
             "supported_reasoning_levels": [{"effort": e} for e in ("none", "thinking")]},
            {"slug": "claude-haiku-4-5", "supported_reasoning_levels": []},
        ],
    }


def test_maps_display_name_and_full_id(sample_payload):
    out = models.map_cvc_models(sample_payload)
    by_id = {m["id"]: m for m in out}
    assert by_id["claude-opus-5-5"]["label"] == "Claude Opus 5.5"
    # The gateway needs the full id; "resolved" is what goes to --model.
    assert by_id["claude-opus-5-5"]["resolved"] == "claude-opus-5-5"
    assert by_id["gpt-6.1-sol"]["label"] == "OpenAI · GPT 6.1 Sol"


def test_efforts_are_per_model_from_the_catalog_cards(sample_payload):
    out = models.map_cvc_models(sample_payload)
    by_id = {m["id"]: m for m in out}
    # Full card set cut to the CLI enum (none/ultra are not --effort values).
    assert by_id["claude-opus-5-5"]["efforts"] == models.CVC_EFFORTS
    assert by_id["gpt-6.1-sol"]["efforts"] == models.CVC_EFFORTS
    # A gap in the card is a gap in the picker: "high" is not a qwen level and
    # offering it is what logged effort high as low in the dashboard.
    assert by_id["qwen3.8-max"]["efforts"] == ["low", "medium", "xhigh"]
    # Levels outside the CLI enum (none/thinking) leave no chip at all.
    assert by_id["minimax-m3.1-flash"]["efforts"] == []
    assert by_id["claude-haiku-4-5"]["efforts"] == []
    # No card for the model — claim nothing.
    assert by_id["broken-no-display"]["efforts"] == []


def test_no_cards_in_payload_means_no_effort_claims():
    # A payload shape without catalog cards must not fall back to guessing
    # generic sets (the pre-13.11.2026 behavior).
    payload = {"data": [{"id": "gpt-6.1-sol", "supports_reasoning": True}]}
    out = models.map_cvc_models(payload)
    assert out[0]["efforts"] == []


def test_drops_entries_without_id(sample_payload):
    out = models.map_cvc_models(sample_payload)
    ids = [m["id"] for m in out]
    assert "orphan, no id" not in ids
    assert len(ids) == 6


def test_empty_or_broken_payload_is_not_fatal():
    assert models.map_cvc_models({}) == []
    assert models.map_cvc_models({"data": "oops"}) == []
    assert models.map_cvc_models(None) == []


def test_desc_falls_back_to_series_or_empty(sample_payload):
    out = models.map_cvc_models(sample_payload)
    by_id = {m["id"]: m for m in out}
    assert by_id["claude-opus-5-5"]["desc"] == "Claude Opus"
    assert by_id["gpt-6.1-sol"]["desc"] == ""
