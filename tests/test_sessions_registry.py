"""TDD: the Jarvis session registry.

The registry is what makes a provider-neutral history possible: Claude Code
scans `~/.claude/projects`, Qoder and Kimi keep their own transcripts, and
none of them can filter "sessions this chat started". The registry records
those ids so history.py can list exactly what Jarvis owns.

Contract (from tools/plans/jarvis-multi-provider.md):
  file $XDG_STATE_HOME/dms-agent/sessions.json (default ~/.local/state/dms-agent)
  shape {provider: {sessionId: {title, workDir, ts}}}
  add(provider, sid, title, workDir) upserts; list(provider) newest-first;
  remove(provider, sid) drops one entry; entries survive a restart;
  concurrent writers lose nothing (flock + atomic replace).
"""
import json
import multiprocessing
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sessions_registry as sr  # noqa: E402

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "REGISTRY_PATH", str(tmp_path / "sessions.json"))
    return sr


def test_add_creates_provider_entry(registry):
    registry.add("claude", "sess-1", "Hello", "/tmp/work")
    data = json.load(open(registry.REGISTRY_PATH))
    assert data["claude"]["sess-1"]["title"] == "Hello"
    assert data["claude"]["sess-1"]["workDir"] == "/tmp/work"
    assert isinstance(data["claude"]["sess-1"]["ts"], (int, float))


def test_add_is_upsert_not_append(registry):
    registry.add("claude", "sess-1", "First", "/a")
    registry.add("claude", "sess-1", "Second", "/b")
    data = json.load(open(registry.REGISTRY_PATH))
    assert len(data["claude"]) == 1
    assert data["claude"]["sess-1"]["title"] == "Second"


def test_list_returns_newest_first(registry):
    registry.add("claude", "old", "Old", "/tmp")
    registry.add("claude", "new", "New", "/tmp")
    listed = registry.list("claude")
    ids = [e["id"] for e in listed]
    assert ids.index("new") < ids.index("old")


def test_list_is_scoped_to_provider(registry):
    registry.add("claude", "c1", "Claude one", "/tmp")
    registry.add("kimi", "k1", "Kimi one", "/tmp")
    ids = [e["id"] for e in registry.list("kimi")]
    assert ids == ["k1"]


def test_remove_drops_one_entry(registry):
    registry.add("claude", "a", "A", "/tmp")
    registry.add("claude", "b", "B", "/tmp")
    registry.remove("claude", "a")
    ids = [e["id"] for e in registry.list("claude")]
    assert ids == ["b"]


def test_remove_unknown_session_is_a_noop(registry):
    registry.add("claude", "a", "A", "/tmp")
    registry.remove("claude", "missing")
    assert len(registry.list("claude")) == 1


def test_corrupt_registry_file_is_treated_as_empty(registry):
    with open(registry.REGISTRY_PATH, "w") as fh:
        fh.write("{not json")
    assert registry.list("claude") == []


def test_missing_registry_file_is_treated_as_empty(registry):
    assert registry.list("claude") == []


def test_title_is_truncated_and_sanitised(registry):
    registry.add("claude", "a", "x" * 500 + "\nnewline", "/tmp")
    entry = registry.list("claude")[0]
    assert len(entry["title"]) <= 200
    assert "\n" not in entry["title"]


def test_rename_updates_title(registry):
    registry.add("claude", "a", "Old", "/tmp")
    registry.rename("claude", "a", "New title")
    assert registry.list("claude")[0]["title"] == "New title"


def test_rename_of_missing_entry_is_a_noop(registry):
    registry.rename("claude", "ghost", "New")
    assert registry.list("claude") == []


def test_add_if_absent_keeps_the_title_of_an_existing_entry(registry):
    """A session is registered the moment its id appears, and every later
    message of that session registers it again: a title given in between
    (rename) must survive."""
    assert registry.add_if_absent("qoder", "a", "First", "/tmp") is True
    assert registry.add_if_absent("qoder", "a", "Second", "/tmp") is True
    assert registry.list("qoder")[0]["title"] == "First"


def test_add_if_absent_of_a_new_entry_creates_it(registry):
    assert registry.add_if_absent("qoder", "a", "Title", "/w") is True
    assert registry.list("qoder")[0]["id"] == "a"


def test_add_if_absent_needs_a_provider_and_an_id(registry):
    assert registry.add_if_absent("", "a", "T", "/w") is False
    assert registry.add_if_absent("qoder", "", "T", "/w") is False
    assert registry.list("qoder") == []


def test_save_leaves_no_temp_files(registry):
    registry.add("claude", "a", "A", "/tmp")
    d = os.path.dirname(registry.REGISTRY_PATH)
    assert [f for f in os.listdir(d) if f.startswith(".sessions-")] == []


def _hammer(path, provider, count):
    sr.REGISTRY_PATH = path
    for i in range(count):
        sr.add(provider, "%s-%d" % (provider, i), "T%d" % i, "/w")


def test_concurrent_adds_do_not_lose_entries(tmp_path):
    """Post-hoc (2026-11-02): the stand and the live DMS wrote one registry at
    once and a lost update dropped a whole provider key; nothing may be lost."""
    path = str(tmp_path / "sessions.json")
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_hammer, args=(path, p, 20))
             for p in ("claude", "cvc", "kimi", "qoder")]
    for pr in procs:
        pr.start()
    for pr in procs:
        pr.join(30)
        assert pr.exitcode == 0
    with open(path) as fh:
        data = json.load(fh)
    for p in ("claude", "cvc", "kimi", "qoder"):
        assert len(data.get(p, {})) == 20, "lost %s entries" % p


def _print_registry_path(env):
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r);"
         "import sessions_registry as s; print(s.REGISTRY_PATH)" % PLUGIN],
        env=env, capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_registry_path_follows_xdg_state_home(tmp_path):
    env = dict(os.environ, XDG_STATE_HOME=str(tmp_path / "state"))
    assert _print_registry_path(env) == str(
        tmp_path / "state" / "dms-agent" / "sessions.json")


def test_registry_path_accepts_tilde_in_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", "~/st")
    assert _print_registry_path(dict(os.environ)) == str(
        tmp_path / "st" / "dms-agent" / "sessions.json")


def test_registry_path_defaults_under_home(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path / "home"))
    env.pop("XDG_STATE_HOME", None)
    assert _print_registry_path(env) == str(
        tmp_path / "home" / ".local" / "state" / "dms-agent" / "sessions.json")


def test_a_corrupt_registry_is_kept_aside_not_destroyed(registry):
    """_load treats a corrupt file as empty; the next write must not silently
    replace every provider's list with the one entry being added."""
    with open(registry.REGISTRY_PATH, "w") as fh:
        fh.write('{"claude": {"sess-1": {"title": "x"')  # truncated
    registry.add("qoder", "s2", "New", "/tmp")
    backups = [p for p in os.listdir(os.path.dirname(registry.REGISTRY_PATH))
               if ".corrupt-" in p]
    assert backups, os.listdir(os.path.dirname(registry.REGISTRY_PATH))
    assert open(os.path.join(os.path.dirname(registry.REGISTRY_PATH), backups[0])).read().startswith('{"claude"')
    assert json.load(open(registry.REGISTRY_PATH))["qoder"]["s2"]["title"] == "New"
