"""TDD: the Antigravity (agy) descriptor in providers.js and i18n login hint."""
import json
import os
import re
import subprocess

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_provider.js")


def run(fn, arg=None):
    return json.loads(subprocess.run(
        ["node", NODE, fn, json.dumps(arg or {})],
        capture_output=True, text=True, check=True, cwd=PLUGIN,
    ).stdout)


def test_agy_descriptor_shape():
    d = run("agy_caps")
    assert d is not None
    assert d["id"] == "agy"
    assert d["title"] == "Antigravity"
    assert d["adapter"] == "acp"
    assert d["bridge"] is True
    assert d["caps"] == {
        "askFirst": True,
        "cost": False,
        "stdinEnabled": True,
        "cancelViaStdin": True,
        "perSessionRestore": False,
        "registryHistory": True,
    }
    assert d["canUseTool"] is False
    assert d["aliasModels"] is False
    assert d["requiresKey"] is False
    assert d["stdinUserFormat"] == {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    }


def test_agy_build_command_flags_and_isolation():
    cmd_ask = run("agy_buildCommand", {
        "bridgeScript": "/opt/dms/bridges/acp_bridge.py",
        "stateDir": "/home/u/.local/state/dms-agent",
        "confirm": True,
    })
    assert "exec python3 '/opt/dms/bridges/acp_bridge.py' agy acp" in cmd_ask
    assert "--gemini-dir '/home/u/.local/state/dms-agent/agy-gemini'" in cmd_ask
    assert "--app-data-dir agy-app" in cmd_ask
    assert "--include-default-customizations=false" in cmd_ask
    assert "--dangerously-skip-permissions" not in cmd_ask
    assert cmd_ask.endswith("2>/dev/null")

    cmd_auto = run("agy_buildCommand", {
        "bridgeScript": "/opt/dms/bridges/acp_bridge.py",
        "stateDir": "/home/u/.local/state/dms-agent",
        "confirm": False,
    })
    assert "--dangerously-skip-permissions" in cmd_auto

    assert run("agy_buildCommand", {"stateDir": "/tmp/s"}) == "exit 3"


def test_agy_cancel_hint_and_keeps_model():
    assert run("cancelMessage", {"id": "agy", "requestId": 12}) == {"type": "cancel"}
    assert run("hintKey", {"id": "agy"}) == "loginHint.agy"

    catalog = [{"id": "claude-opus-5-5"}, {"id": "gemini-3.8-flash"}]
    assert run("keepsModel", {"provider": "agy", "models": catalog, "saved": "opus"}) is False
    assert run("keepsModel", {"provider": "agy", "models": catalog, "saved": "gemini-3.8-flash"}) is True


def test_i18n_has_login_hint_for_agy():
    src = open(os.path.join(PLUGIN, "i18n.js"), encoding="utf-8").read()
    # Both English and Russian tables must define loginHint.agy.
    assert len(re.findall(r'"loginHint\.agy"\s*:', src)) == 2
