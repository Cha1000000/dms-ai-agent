"""Post-hoc: history.py delete must drop the session from the registry too.

Bug found in the stage-2 CVC smoke (2026-11-01): deleting a transcript left
its sessions.json entry behind forever — delete only removed the .jsonl and
called forget_synced, while rename/delete-all also touch the registry.
"""
import json
import os
import re
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_history(home, cwd, *args):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "history.py"), *args],
        cwd=str(cwd), env=env, capture_output=True, text=True,
    )


def make_agent_session(home, cwd, sid):
    """A minimal transcript is_agent_session() accepts (entrypoint sdk-cli)."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    proj = home / ".claude" / "projects" / slug
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / (sid + ".jsonl")
    path.write_text(
        '{"type":"system","entrypoint":"sdk-cli"}\n'
        '{"type":"user","message":{"content":"Hello there"}}\n'
    )
    return path


def registry_data(home):
    path = home / ".local" / "state" / "dms-agent" / "sessions.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def test_delete_removes_registry_entry_too(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "11111111-2222-3333-4444-555555555555"
    make_agent_session(home, cwd, sid)

    run_history(home, cwd, "--provider", "cvc", "list")
    assert sid in registry_data(home).get("cvc", {})

    out = run_history(home, cwd, "--provider", "cvc", "delete", sid)
    assert json.loads(out.stdout) == {"deleted": 1}
    assert sid not in registry_data(home).get("cvc", {})


def test_delete_of_unknown_session_reports_zero(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True)
    out = run_history(home, cwd, "--provider", "cvc", "delete", "no-such-id")
    assert json.loads(out.stdout) == {"deleted": 0}
