"""TDD: the 9Router (cc9) provider.

The user runs Claude Code through the cc9 wrapper — the stock CLI pointed at
the local 9Router gateway. Its catalog is the gateway's aggregate (181 ids
under ~/.claude-cc9), and it is only visible when the CLI's own config dir is
the cc9 one: DMS started from systemd inherits no cc9 environment, so the
stock CLI reports the five native Claude models instead. The provider therefore
runs the cc9 wrapper itself, and its catalog is read from the wrapper, not
from whatever `claude` happens to be on PATH.

Contract:
  - the provider exists and speaks the claude stream-json protocol
  - it keeps the claude capabilities (ask-first, cost, stdin, cancel,
    per-session restore): the wrapper passes the flags through
  - it runs `cc9`, not `claude`
  - the catalog comes from the cc9 wrapper and drops the Combo presets, the
    group headers, the Tokenator namespace and Fable — the same rules as for
    any other harness aggregate ("Никаких Комбо и моделей Токенатора в
    Джарвисе быть не должно")
  - the bare "opus"/"sonnet"/"haiku" aliases are not offered: in the cc9
    catalog they are its own presets and resolve to the Combo
"""
import json
import os
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(os.path.dirname(__file__), "run_provider.js")

run = lambda fn, arg=None: json.loads(subprocess.run(
    ["node", NODE, fn, json.dumps(arg or {})], capture_output=True, text=True, check=True,
    cwd=PLUGIN,
).stdout)


def test_the_provider_is_registered():
    caps = run("cc9_caps")
    assert caps["id"] == "cc9"
    assert caps["title"]
    assert caps["canUseTool"] is True


def test_it_keeps_the_claude_capabilities():
    caps = run("cc9_caps")["caps"]
    assert caps["askFirst"] is True
    assert caps["cost"] is True
    assert caps["stdinEnabled"] is True
    assert caps["cancelViaStdin"] is True
    assert caps["perSessionRestore"] is True


def test_it_has_no_bare_aliases():
    # In the cc9 catalog "opus" and "sonnet" are its own presets — the Combo.
    assert run("cc9_caps")["aliasModels"] is False


def test_the_command_runs_the_cc9_wrapper():
    cmd = run("cc9_buildCommand", {"model": "cvc/claude-opus-5-5", "effort": "high",
                                    "confirm": True, "systemPrompt": "hi", "prompt": "p"})
    assert "cc9" in cmd
    assert "claude " not in cmd.replace("cc9 ", "")
    assert "--model 'cvc/claude-opus-5-5'" in cmd
    assert "--effort 'high'" in cmd
    assert "--permission-prompt-tool stdio" in cmd


def test_the_catalog_comes_from_the_cc9_wrapper(tmp_path, monkeypatch):
    """The CLI on PATH may be the stock one — its catalog is the five native
    models. The wrapper's catalog is what the provider must offer."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        catalog = [{"value": "cvc/claude-opus-5-5", "displayName": "Claude Opus 5.5",
                    "resolvedModel": "cvc/claude-opus-5-5",
                    "supportedEffortLevels": ["low", "high"]}]
        payload = json.dumps({"type": "control_response", "response": {
            "response": {"models": catalog}}})
        return type("R", (), {"stdout": payload + "\n", "returncode": 0})()

    monkeypatch.setattr(models.subprocess, "run", fake_run)
    out = models.fetch_models_for("cc9")
    assert calls, "the wrapper was not called"
    assert calls[0][0].split()[0].endswith("cc9"), calls[0]
    assert [m["id"] for m in out] == ["cvc/claude-opus-5-5"], out


def test_the_catalog_drops_combos_groups_tokenator_and_fable(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        catalog = [
            {"value": "default", "displayName": "Default"},
            {"value": "cc9-group:cvc", "displayName": "── cvc ──"},
            {"value": "claude-cowork-combo", "displayName": "Комбо"},
            {"value": "free-models", "displayName": "Все бесплатные"},
            {"value": "tk-free", "displayName": "Бесплатные Tokenator"},
            {"value": "tokenator-paid", "displayName": "Платные Tokenator"},
            {"value": "tk/claude-opus-5-5", "displayName": "Opus (Tokenator)"},
            {"value": "cvc/claude-fable-5", "displayName": "Fable"},
            {"value": "cvc/claude-opus-5-5", "displayName": "Claude Opus 5.5"},
            {"value": "kc/google/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash"},
        ]
        payload = json.dumps({"type": "control_response", "response": {
            "response": {"models": catalog}}})
        return type("R", (), {"stdout": payload + "\n", "returncode": 0})()

    monkeypatch.setattr(models.subprocess, "run", fake_run)
    out = models.fetch_models_for("cc9")
    assert [m["id"] for m in out] == ["cvc/claude-opus-5-5",
                                      "kc/google/gemini-2.5-flash"], out


def test_the_known_providers_include_cc9():
    assert "cc9" in models.KNOWN_PROVIDERS


def test_history_knows_cc9():
    """The wrapper keeps its transcripts in the shared ~/.claude/projects store
    (the cc9 config dir symlinks it), so the history must find them."""
    out = subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "history.py"), "--provider", "cc9", "list"],
        capture_output=True, text=True, env=dict(os.environ, HOME="/tmp/cc9-home"))
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == []
