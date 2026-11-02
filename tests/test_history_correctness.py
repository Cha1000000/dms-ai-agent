"""TDD: the correctness of history.py's session scan and registry handling.

Four defects found in the review of 2026-11-02:

  C1  is_agent_session() returned on the first line that merely mentions
      "entrypoint" — a session whose own text says the word was dropped from
      the history. The field itself decides, and the scan must go on.
  C2  the file could vanish between the glob and the read (deleted from the
      other panel) → an unhandled FileNotFoundError emptied the whole history.
  C3  every read wrote to the registry, which refreshed the timestamp of
      every session — the panel's order jumped on every poll. A read must not
      move anything.
  C4  delete-all for claude/cvc dropped the registry entries of every
      directory, while the panel only ever shows the current one.
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


def project_dir(home, cwd):
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    proj = home / ".claude" / "projects" / slug
    proj.mkdir(parents=True, exist_ok=True)
    return proj


def write_session(home, cwd, sid, lines):
    path = project_dir(home, cwd) / (sid + ".jsonl")
    path.write_text("".join(line + "\n" for line in lines))
    return path


def registry_data(home):
    path = home / ".local" / "state" / "dms-agent" / "sessions.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# --- C1: the field decides, not a word in the text ---

def test_a_session_whose_text_mentions_entrypoint_is_still_listed(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-1111-2222-3333-444444444444"
    # The user asks about the entrypoint field; the session itself is an
    # agent session and must not be dropped from the history.
    write_session(home, cwd, sid, [
        '{"type":"user","message":{"content":"what is the entrypoint field?"}}',
        '{"type":"system","entrypoint":"sdk-cli"}',
    ])
    out = run_history(home, cwd, "--provider", "claude", "list")
    assert json.loads(out.stdout), out.stdout
    assert sid in [r["id"] for r in json.loads(out.stdout)]


def test_an_interactive_session_is_left_out(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "bbbbbbbb-1111-2222-3333-444444444444"
    write_session(home, cwd, sid, [
        '{"type":"system","entrypoint":"cli"}',
        '{"type":"user","message":{"content":"hello"}}',
    ])
    out = run_history(home, cwd, "--provider", "claude", "list")
    assert sid not in [r["id"] for r in json.loads(out.stdout)], out.stdout


# --- C2: a file that vanishes during the scan must not break the history ---

def test_a_vanishing_file_does_not_empty_the_history(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "cccccccc-1111-2222-3333-444444444444"
    write_session(home, cwd, sid, [
        '{"type":"system","entrypoint":"sdk-cli"}',
        '{"type":"user","message":{"content":"hello"}}',
    ])
    # A file that is not a readable transcript at all — the scan must skip it
    # and still list the good session.
    (project_dir(home, cwd) / "broken.jsonl").write_text("{not json\n")
    out = run_history(home, cwd, "--provider", "claude", "list")
    assert out.returncode == 0, out.stderr
    ids = [r["id"] for r in json.loads(out.stdout)]
    assert sid in ids, out.stdout


# --- C3: a read must not move the sessions ---

def test_listing_does_not_rewrite_the_registry(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "dddddddd-1111-2222-3333-444444444444"
    write_session(home, cwd, sid, [
        '{"type":"system","entrypoint":"sdk-cli"}',
        '{"type":"user","message":{"content":"hello"}}',
    ])
    run_history(home, cwd, "--provider", "claude", "list")
    first = registry_data(home).get("claude", {}).get(sid)
    assert first is not None, registry_data(home)

    run_history(home, cwd, "--provider", "claude", "list")
    second = registry_data(home).get("claude", {}).get(sid)
    # A read that rewrote the entry would move its timestamp, and with it the
    # session's place in the panel.
    assert second["ts"] == first["ts"], (first, second)


def test_a_renamed_session_keeps_its_name_after_a_listing(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "eeeeeeee-1111-2222-3333-444444444444"
    write_session(home, cwd, sid, [
        '{"type":"system","entrypoint":"sdk-cli"}',
        '{"type":"user","message":{"content":"hello"}}',
    ])
    run_history(home, cwd, "--provider", "claude", "list")
    run_history(home, cwd, "--provider", "claude", "rename", sid, "My name")
    run_history(home, cwd, "--provider", "claude", "list")
    assert registry_data(home).get("claude", {}).get(sid)["title"] == "My name"


# --- C4: delete-all only clears the current directory ---

def test_delete_all_keeps_the_entries_of_other_directories(tmp_path):
    home = tmp_path / "home"
    here = tmp_path / "work"
    there = tmp_path / "other"
    here.mkdir(parents=True)
    there.mkdir(parents=True)
    write_session(home, here, "11111111-aaaa-bbbb-cccc-555555555555", [
        '{"type":"system","entrypoint":"sdk-cli"}',
        '{"type":"user","message":{"content":"here"}}',
    ])
    write_session(home, there, "22222222-aaaa-bbbb-cccc-555555555555", [
        '{"type":"system","entrypoint":"sdk-cli"}',
        '{"type":"user","message":{"content":"there"}}',
    ])
    run_history(home, here, "--provider", "claude", "list")
    run_history(home, there, "--provider", "claude", "list")

    run_history(home, here, "--provider", "claude", "delete-all")
    claude = registry_data(home).get("claude", {})
    assert "11111111-aaaa-bbbb-cccc-555555555555" not in claude
    # The other directory's session is still listed in its own panel.
    assert "22222222-aaaa-bbbb-cccc-555555555555" in claude, claude


# --- E2: Claude Code and CheapVibeCode share one transcript store ---

def test_deleting_under_one_gateway_clears_the_other_one_too(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "ffffffff-1111-2222-3333-444444444444"
    write_session(home, cwd, sid, [
        '{"type":"system","entrypoint":"sdk-cli"}',
        '{"type":"user","message":{"content":"hello"}}',
    ])
    # The same session is known to both gateways.
    run_history(home, cwd, "--provider", "claude", "list")
    run_history(home, cwd, "--provider", "cvc", "list")
    data = registry_data(home)
    assert sid in data.get("claude", {})
    assert sid in data.get("cvc", {})

    run_history(home, cwd, "--provider", "cvc", "delete", sid)
    data = registry_data(home)
    # The transcript is one file, so the session is gone for both.
    assert sid not in data.get("cvc", {})
    assert sid not in data.get("claude", {}), data
