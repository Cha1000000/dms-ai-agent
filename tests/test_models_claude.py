"""TDD: the Claude model list, and the filter over a harness wrapper's catalog.

The claude provider takes its list from the CLI's initialize response. When
`claude` on PATH is a wrapper (cc9), that catalog is a gateway aggregate: group
headers, combo presets and the Tokenator namespace are not models and must not
reach the picker. Contract: "Никаких Комбо и моделей Токенатора в Джарвисе
быть не должно", while a free model the user picked by hand stays.
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
        assert not models.native_claude_id(mid), mid


def test_group_headers_and_tokenator_namespace_are_dropped():
    assert not models.native_claude_id("cc9-group:anthropic")
    assert not models.native_claude_id("tk/claude-opus-5-5")


def test_gateway_namespaced_ids_are_not_claude_models():
    # Superseded 2026-11-02: this used to be kept "because the user picked it
    # by hand", but every gateway id is listed by its own provider and none is a
    # Claude Code model, so none belongs in this picker.
    assert not models.native_claude_id("cl/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
    assert not models.native_claude_id("cl/xingchen-agi/xing4.0-29b-a4b:free")


def test_native_ids_survive():
    for mid in ["claude-opus-5-5", "claude-sonnet-5-5", "opus", "haiku"]:
        assert models.native_claude_id(mid), mid


def test_aliases_are_added_when_the_catalog_lacks_them():
    out = models.with_claude_aliases([{"id": "claude-opus-5-5"}])
    assert [m["id"] for m in out] == ["claude-opus-5-5", "opus", "sonnet", "haiku"]


def test_aliases_are_not_duplicated_when_the_catalog_has_them():
    out = models.with_claude_aliases([{"id": "opus"}, {"id": "haiku"}])
    assert [m["id"] for m in out] == ["opus", "haiku", "sonnet"]


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


def test_fetch_keeps_native_models_and_drops_the_gateway_aggregate(tmp_path):
    catalog = [
        {"value": "claude-opus-5-5", "displayName": "Opus 5.5",
         "supportedEffortLevels": ["low", "high"]},
        {"value": "cc9-group:anthropic", "displayName": "Anthropic"},
        {"value": "claude-cowork-combo", "displayName": "Комбо"},
        {"value": "tk/claude-sonnet-5-5", "displayName": "Sonnet (Tokenator)"},
        {"value": "cvc/claude-sonnet-5-5", "displayName": "Sonnet via gateway"},
    ]
    out = _run(_stub_claude(tmp_path, catalog), tmp_path)
    assert out.returncode == 0, out.stderr
    ids = [m["id"] for m in json.loads(out.stdout)]
    assert ids == ["claude-opus-5-5", "opus", "sonnet", "haiku"]


def test_gateway_catalog_does_not_replace_native_models(tmp_path):
    """Live 2026-11-02: with 9Router on PATH the claude picker listed 101
    gateway ids (cvc/*, ag/*, qd/*, …) and no native Claude model at all.
    The provider is "Claude Code"; a gateway is a different provider, not a
    longer list of this one. Native entries stay, gateway ids go, aliases fill in.
    """
    catalog = [
        {"value": "cvc/claude-opus-5-5", "displayName": "Opus 5.5"},
        {"value": "cvc/claude-fable-5", "displayName": "Fable 5"},
        {"value": "cvc/gpt-6-sol", "displayName": "GPT-6 Sol"},
        {"value": "ag/gemini-3.8-flash-low", "displayName": "Gemini"},
        {"value": "qd/qfmodel", "displayName": "Qwen"},
        {"value": "cl/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
         "displayName": "Nemotron (free)"},
    ]
    out = _run(_stub_claude(tmp_path, catalog), tmp_path)
    assert out.returncode == 0, out.stderr
    ids = [m["id"] for m in json.loads(out.stdout)]
    assert ids == ["opus", "sonnet", "haiku"], ids


def test_gateway_catalog_prefers_the_real_claude_catalog(tmp_path):
    """When the wrapper also lists native ids, only those are shown — the
    gateway's own ids never pad the list."""
    catalog = [
        {"value": "claude-opus-5-5", "displayName": "Opus 5.5"},
        {"value": "cvc/claude-sonnet-5-5", "displayName": "Sonnet via gateway"},
        {"value": "tk/claude-opus-5", "displayName": "Opus via Tokenator"},
    ]
    out = _run(_stub_claude(tmp_path, catalog), tmp_path)
    ids = [m["id"] for m in json.loads(out.stdout)]
    assert ids == ["claude-opus-5-5", "opus", "sonnet", "haiku"], ids


def test_gateway_ids_are_not_native_claude_models():
    assert not models.native_claude_id("cvc/claude-opus-5-5")
    assert not models.native_claude_id("cvc/claude-fable-5")
    assert not models.native_claude_id("cvc/gpt-6-sol")
    assert not models.native_claude_id("qd/qfmodel")
