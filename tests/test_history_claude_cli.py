"""TDD: history.py support for custom `claude-cli` registry providers."""
import json
import os
import re
import subprocess
import sys

import pytest

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN)

import registry as prov_reg  # noqa: E402
import sessions_registry as sr  # noqa: E402


def project_dir(root, cwd):
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    proj = root / "projects" / slug
    proj.mkdir(parents=True, exist_ok=True)
    return proj


def write_transcript(claude_root, cwd, sid, records):
    path = project_dir(claude_root, cwd) / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    return path


def run_history(home, cwd, *args):
    env = dict(os.environ, HOME=str(home), XDG_STATE_HOME=str(home / ".local" / "state"))
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "history.py"), *args],
        cwd=str(cwd), env=env, capture_output=True, text=True,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    state = home / ".local" / "state"
    work = tmp_path / "work"
    other = tmp_path / "other"
    home.mkdir()
    work.mkdir()
    other.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setattr(sr, "REGISTRY_PATH", sr._registry_path())
    monkeypatch.setattr(prov_reg, "REGISTRY_PATH", prov_reg._registry_path())
    prov_reg.set_provider("cc9", {
        "title": "Claude Wrapper",
        "adapter": "claude-cli",
        "command": ["cc9"],
    })
    return {
        "home": home,
        "state": state,
        "claude_root": home / ".claude",
        "work": work,
        "other": other,
    }


def test_claude_cli_restore_reads_transcript_model_effort_and_foreign_dir(env):
    sid = "11111111-1111-4111-8111-111111111111"
    write_transcript(env["claude_root"], env["other"], sid, [
        {"type": "system", "entrypoint": "sdk-cli"},
        {"type": "user", "message": {"content": "Hello cc9"}},
        {
            "type": "assistant",
            "requestedModel": "minimax-m3.1-flash",
            "effort": "high",
            "message": {"content": [{"type": "text", "text": "Hi there"}]},
        },
    ])
    sr.add("cc9", sid, "Hello cc9", str(env["other"]))

    out = run_history(env["home"], env["work"], "--provider", "cc9", "restore", sid, str(env["other"]))
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data == {
        "messages": [
            {"role": "user", "content": "Hello cc9"},
            {"role": "assistant", "content": "Hi there"},
        ],
        "model": "minimax-m3.1-flash",
        "effort": "high",
        "originDir": str(env["other"]),
    }


def test_claude_cli_respects_custom_claude_config_dir(env):
    custom_root = env["home"] / ".cc-alt"
    prov_reg.set_provider("cc-alt", {
        "title": "Alt Claude",
        "adapter": "claude-cli",
        "command": ["env", f"CLAUDE_CONFIG_DIR={custom_root}", "claude"],
    })
    sid = "22222222-2222-4222-8222-222222222222"
    write_transcript(custom_root, env["work"], sid, [
        {"type": "system", "entrypoint": "sdk-cli"},
        {"type": "user", "message": {"content": "Alt question"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Alt answer"}]}},
    ])
    sr.add("cc-alt", sid, "Alt question", str(env["work"]))

    data = json.loads(run_history(env["home"], env["work"], "--provider", "cc-alt", "restore", sid).stdout)
    assert data["messages"] == [
        {"role": "user", "content": "Alt question"},
        {"role": "assistant", "content": "Alt answer"},
    ]


def test_claude_cli_rename_writes_transcript_and_syncs_shared_registry(env):
    sid = "33333333-3333-4333-8333-333333333333"
    path = write_transcript(env["claude_root"], env["work"], sid, [
        {"type": "system", "entrypoint": "sdk-cli"},
        {"type": "user", "message": {"content": "Original"}},
    ])
    sr.add("cc9", sid, "Original", str(env["work"]))
    sr.add("claude", sid, "Original", str(env["work"]))

    out = run_history(env["home"], env["work"], "--provider", "cc9", "rename", sid, "Renamed Chat")
    assert json.loads(out.stdout) == {"renamed": 1}

    text = path.read_text(encoding="utf-8")
    assert '"customTitle":"Renamed Chat"' in text
    assert '"agentName":"Renamed Chat"' in text
    assert sr.list("cc9")[0]["title"] == "Renamed Chat"
    assert sr.list("claude")[0]["title"] == "Renamed Chat"


def test_claude_cli_delete_removes_transcript_syncs_shared_and_cleans_stale(env):
    sid = "44444444-4444-4444-8444-444444444444"
    stale_sid = "55555555-5555-4555-8555-555555555555"
    path = write_transcript(env["claude_root"], env["work"], sid, [
        {"type": "system", "entrypoint": "sdk-cli"},
        {"type": "user", "message": {"content": "Delete me"}},
    ])
    sidecar = path.parent / sid
    sidecar.mkdir()
    (sidecar / "note.txt").write_text("x")

    sr.add("cc9", sid, "Delete me", str(env["work"]))
    sr.add("claude", sid, "Delete me", str(env["work"]))
    sr.add("cvc", sid, "Delete me", str(env["work"]))
    sr.add("cc9", stale_sid, "Already gone", str(env["work"]))

    out = run_history(env["home"], env["work"], "--provider", "cc9", "delete", sid)
    assert json.loads(out.stdout) == {"deleted": 1, "removed": 1}
    assert not path.exists()
    assert not sidecar.exists()
    assert sr.list("claude") == []
    assert sr.list("cvc") == []
    assert [e["id"] for e in sr.list("cc9")] == [stale_sid]

    # Deleting a stale row whose transcript is already missing still cleans the registry.
    out_stale = run_history(env["home"], env["work"], "--provider", "cc9", "delete", stale_sid)
    assert json.loads(out_stale.stdout) == {"deleted": 1, "removed": 1}
    assert sr.list("cc9") == []


def test_claude_cli_refuses_to_delete_interactive_session(env):
    sid = "66666666-6666-4666-8666-666666666666"
    path = write_transcript(env["claude_root"], env["work"], sid, [
        {"type": "system", "entrypoint": "cli"},
        {"type": "user", "message": {"content": "Interactive TUI"}},
    ])
    sr.add("cc9", sid, "Interactive TUI", str(env["work"]))

    out = run_history(env["home"], env["work"], "--provider", "cc9", "delete", sid)
    assert json.loads(out.stdout) == {"deleted": 0, "removed": 0}
    assert path.is_file()
    assert len(sr.list("cc9")) == 1


def test_claude_cli_delete_all_scopes_to_cwd_and_syncs_shared(env):
    sid_here = "77777777-7777-4777-8777-777777777777"
    sid_other = "88888888-8888-4888-8888-888888888888"
    p_here = write_transcript(env["claude_root"], env["work"], sid_here, [
        {"type": "system", "entrypoint": "sdk-cli"},
        {"type": "user", "message": {"content": "Here"}},
    ])
    p_other = write_transcript(env["claude_root"], env["other"], sid_other, [
        {"type": "system", "entrypoint": "sdk-cli"},
        {"type": "user", "message": {"content": "Other"}},
    ])
    sr.add("cc9", sid_here, "Here", str(env["work"]))
    sr.add("claude", sid_here, "Here", str(env["work"]))
    sr.add("cc9", sid_other, "Other", str(env["other"]))

    out = run_history(env["home"], env["work"], "--provider", "cc9", "delete-all")
    assert json.loads(out.stdout) == {"deleted": 1, "failed": 0}
    assert not p_here.exists()
    assert p_other.is_file()
    assert sr.list("claude") == []
    assert [e["id"] for e in sr.list("cc9")] == [sid_other]
