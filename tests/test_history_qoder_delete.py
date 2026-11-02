"""TDD: deleting a Qoder session goes through the CLI (history.py).

Qoder keeps a transcript and a sidecar directory per session, and its CLI
knows how to remove both. Doing it by hand leaves the CLI's own session index
pointing at a session that is gone, and the next `--resume` finds a broken
one. The plugin therefore asks the CLI:

  qodercli --list-sessions          -> "  N. Title (age) [uuid]"
  qodercli --delete-session <N>     -> removes the session

The index comes from the list, matched on the uuid in the brackets — never on
the position, which changes as soon as another session is added.
"""
import json
import os
import re
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_history(home, cwd, *args, path=None):
    env = dict(os.environ, HOME=str(home))
    env.pop("XDG_STATE_HOME", None)
    if path:
        env["PATH"] = str(path) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, "history.py"), *args],
        cwd=str(cwd), env=env, capture_output=True, text=True,
    )


def make_qoder_session(home, cwd, sid):
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    proj = home / ".qoder" / "projects" / slug
    proj.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "workspace-directories", "directories": [str(cwd)], "sessionId": sid},
        {"type": "user", "sessionId": sid,
         "message": {"role": "user", "content": [{"type": "text", "text": "Привет"}]}},
        {"type": "assistant", "sessionId": sid,
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Готово"}]}},
    ]
    path = proj / (sid + ".jsonl")
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")
    (proj / sid).mkdir(exist_ok=True)
    return path


def fake_qodercli(tmp_path, sessions, log):
    """A qodercli that lists the given sessions and deletes the asked index."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "qodercli"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "log = %r\n"
        "sessions = %r\n"
        "args = sys.argv[1:]\n"
        "if '--list-sessions' in args:\n"
        "    for i, (title, uid) in enumerate(sessions, start=1):\n"
        "        print('  %%d. %%s (2h ago) [%%s]' %% (i, title, uid))\n"
        "    sys.exit(0)\n"
        "if '--delete-session' in args:\n"
        "    idx = args[args.index('--delete-session') + 1]\n"
        "    open(log, 'a').write('delete %%s\\n' %% idx)\n"
        "    uid = sessions[int(idx) - 1][1]\n"
        "    open(log, 'a').write('removed %%s\\n' %% uid)\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n" % (str(log), sessions)
    )
    script.chmod(0o755)
    return bin_dir


def registry_data(home):
    path = home / ".local" / "state" / "dms-agent" / "sessions.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def test_delete_asks_the_cli_to_delete_the_session(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    other = "11111111-2222-3333-4444-555555555555"
    make_qoder_session(home, cwd, sid)
    run_history(home, cwd, "--provider", "qoder", "register", sid, "Привет")

    log = tmp_path / "calls.log"
    bin_dir = fake_qodercli(tmp_path, [("Привет", sid), ("Другая", other)], log)

    out = run_history(home, cwd, "--provider", "qoder", "delete", sid, path=bin_dir)
    assert json.loads(out.stdout) == {"deleted": 1}, out.stdout
    calls = log.read_text()
    # The index comes from the list, and it is the one that belongs to the
    # session being deleted — the second entry must not be touched.
    assert "delete 1" in calls, calls
    assert "removed " + sid in calls, calls
    assert "removed " + other not in calls, calls


def test_delete_finds_the_right_index_when_the_order_differs(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "cccccccc-dddd-eeee-ffff-000000000000"
    make_qoder_session(home, cwd, sid)
    run_history(home, cwd, "--provider", "qoder", "register", sid, "Привет")

    log = tmp_path / "calls.log"
    # The session is not the first one in the CLI's list.
    bin_dir = fake_qodercli(tmp_path, [
        ("Другая", "11111111-2222-3333-4444-555555555555"),
        ("Привет", sid),
    ], log)

    out = run_history(home, cwd, "--provider", "qoder", "delete", sid, path=bin_dir)
    assert json.loads(out.stdout) == {"deleted": 1}, out.stdout
    calls = log.read_text()
    assert "delete 2" in calls, calls
    assert "removed " + sid in calls, calls


def test_the_registry_entry_goes_even_without_the_cli(tmp_path):
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "dddddddd-eeee-ffff-0000-111111111111"
    make_qoder_session(home, cwd, sid)
    run_history(home, cwd, "--provider", "qoder", "register", sid, "Привет")

    # No qodercli on PATH: the plugin's own record of the session must still
    # be dropped, so the panel does not offer a session that is not there.
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    out = run_history(home, cwd, "--provider", "qoder", "delete", sid, path=empty)
    assert json.loads(out.stdout) == {"deleted": 0}, out.stdout
    assert sid not in registry_data(home).get("qoder", {})


def test_delete_of_a_session_the_registry_does_not_know_is_refused(tmp_path):
    """An interactive Qoder session looks exactly like ours in the transcript
    store — only the registry knows which sessions this chat owns."""
    home, cwd = tmp_path / "home", tmp_path / "work"
    cwd.mkdir(parents=True)
    sid = "eeeeeeee-ffff-0000-1111-222222222222"
    make_qoder_session(home, cwd, sid)
    log = tmp_path / "calls.log"
    bin_dir = fake_qodercli(tmp_path, [("Привет", sid)], log)
    out = run_history(home, cwd, "--provider", "qoder", "delete", sid, path=bin_dir)
    assert json.loads(out.stdout) == {"deleted": 0}, out.stdout
    assert not log.exists() or log.read_text() == ""
