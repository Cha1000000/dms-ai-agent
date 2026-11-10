"""TDD: the Claude model list, and the filter over a harness wrapper's catalog.

The claude provider takes its list from the CLI's initialize response. When
`claude` on PATH is a harness wrapper, that catalog is a gateway
aggregate: the group headers are sections, not models, and the Combo presets
and the Tokenator namespace must not reach the picker. Contract: "Никаких
Комбо и моделей Токенатора в Джарвисе быть не должно", while every real
model of the gateway — the one the user actually runs — stays selectable.
"""
import json
import os
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_combo_presets_are_not_models():
    for mid in ["claude-cowork-combo", "free-models", "tk-free", "tokenator-paid"]:
        assert not models.claude_model_id(mid), mid


def test_group_headers_are_not_models():
    assert not models.claude_model_id("wrap-group:anthropic")
    assert not models.claude_model_id("wrap-group:cvc")


def test_tokenator_models_are_not_in_the_picker():
    # tk/ is the Tokenator namespace of the 9Router — the rule says no
    # Tokenator models in Jarvis, and the free ones are reachable as their
    # own gateway ids (kc/…, cvc/…).
    assert not models.claude_model_id("tk/claude-opus-5-5")
    assert not models.claude_model_id("tk/gemini-3.1-flash-lite")


def test_gateway_models_of_the_other_providers_stay():
    # The aggregate is the catalog of the harness the user runs: these ids are
    # exactly what its --model takes, so they are what the picker must offer.
    for mid in ["cvc/claude-opus-5-5", "ag/gemini-3.8-flash-low", "qd/qfmodel",
                "kc/google/gemini-2.5-flash", "cl/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
                "kgw/openai/gpt-5.5", "kimi/kimi-k3", "openrouter/minimax/minimax-m3:free"]:
        assert models.claude_model_id(mid), mid


def test_native_ids_survive():
    for mid in ["claude-opus-5-5", "claude-sonnet-5-5", "opus", "haiku"]:
        assert models.claude_model_id(mid), mid


def test_fable_is_left_out():
    assert not models.claude_model_id("claude-fable-5-1[1m]")
    assert not models.claude_model_id("claude-fable-5")
    assert not models.claude_model_id("cvc/claude-fable-5")


def test_aliases_are_added_when_the_catalog_lacks_them():
    out = models.with_claude_aliases([{"id": "claude-opus-5-5"}])
    assert [m["id"] for m in out] == ["claude-opus-5-5", "opus", "sonnet", "haiku"]


def test_aliases_are_not_duplicated_when_the_catalog_has_them():
    out = models.with_claude_aliases([{"id": "opus"}, {"id": "haiku"}])
    assert [m["id"] for m in out] == ["opus", "haiku", "sonnet"]


def test_a_gateway_catalog_gets_no_claude_aliases():
    # With a harness on PATH the bare aliases are its own presets: "opus" and
    # "sonnet" resolve to the Combo, and the Combo must not be in Jarvis. The
    # real models of the aggregate are listed instead.
    out = models.with_claude_aliases([{"id": "cvc/claude-opus-5-5"},
                                      {"id": "kc/google/gemini-2.5-flash"}])
    assert [m["id"] for m in out] == ["cvc/claude-opus-5-5", "kc/google/gemini-2.5-flash"]


def _stub_claude(tmp_path, catalog):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    response = json.dumps({"type": "control_response", "response": {
        "response": {"models": catalog}}})
    stub = bin_dir / "claude"
    stub.write_text("#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' '" + response + "'\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run(bin_dir, tmp_path):
    env = dict(os.environ, HOME=str(tmp_path / "home"), XDG_CACHE_HOME=str(tmp_path / "cache"),
               PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    env.pop("XDG_STATE_HOME", None)
    return subprocess.run([sys.executable, os.path.join(PLUGIN, "models.py")],
                          env=env, capture_output=True, text=True)


def test_fetch_keeps_the_real_models_and_drops_the_rest(tmp_path):
    catalog = [
        {"value": "claude-opus-5-5", "displayName": "Opus 5.5",
         "supportedEffortLevels": ["low", "high"]},
        {"value": "wrap-group:anthropic", "displayName": "Anthropic"},
        {"value": "claude-cowork-combo", "displayName": "Комбо"},
        {"value": "tk/claude-sonnet-5-5", "displayName": "Sonnet (Tokenator)"},
        {"value": "cvc/claude-sonnet-5-5", "displayName": "Sonnet via gateway"},
    ]
    out = _run(_stub_claude(tmp_path, catalog), tmp_path)
    assert out.returncode == 0, out.stderr
    ids = [m["id"] for m in json.loads(out.stdout)]
    assert ids == ["claude-opus-5-5", "cvc/claude-sonnet-5-5"]


def test_the_harness_aggregate_reaches_the_picker(tmp_path):
    """Live 2026-11-03: with 9Router on PATH the CLI reports 181 entries —
    group headers, Combo presets, the Tokenator namespace and the real models
    of every gateway. The picker must show the last ones: they are what the
    harness' --model takes.
    """
    catalog = [
        {"value": "default", "displayName": "Default (recommended)"},
        {"value": "wrap-group:combo", "displayName": "── Комбо (фолбэк) ──"},
        {"value": "claude-cowork-combo", "displayName": "Комбо (по умолчанию)"},
        {"value": "free-models", "displayName": "Все бесплатные"},
        {"value": "tk-free", "displayName": "Только бесплатные Tokenator"},
        {"value": "tokenator-paid", "displayName": "💰 Комбо платных Tokenator"},
        {"value": "wrap-group:cvc", "displayName": "── CheapVibeCode (cvc) ──"},
        {"value": "cvc/claude-opus-5-5", "displayName": "Claude Opus 5.5"},
        {"value": "tk/claude-opus-5-5", "displayName": "Opus (Tokenator)"},
        {"value": "kc/google/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash"},
    ]
    out = _run(_stub_claude(tmp_path, catalog), tmp_path)
    assert out.returncode == 0, out.stderr
    ids = [m["id"] for m in json.loads(out.stdout)]
    assert ids == ["cvc/claude-opus-5-5", "kc/google/gemini-2.5-flash"], ids


def test_a_native_catalog_keeps_the_aliases(tmp_path):
    catalog = [
        {"value": "claude-fable-5-1[1m]", "displayName": "Fable 5.1"},
        {"value": "opus", "displayName": "Opus"},
        {"value": "sonnet", "displayName": "Sonnet"},
        {"value": "haiku", "displayName": "Haiku"},
    ]
    out = _run(_stub_claude(tmp_path, catalog), tmp_path)
    assert out.returncode == 0, out.stderr
    ids = [m["id"] for m in json.loads(out.stdout)]
    assert ids == ["opus", "sonnet", "haiku"], ids
