"""TDD: the Python layer's edge cases (provider_secrets.py, models.py, history.py).

  E1  is_signed_in("claude") answered True for any failure, so a CLI that is
      signed out with a non-JSON answer passed the check and the chat failed
      with a wall of auth errors. "No answer" and "answered: not signed in"
      are different.
  E3  the registry's lock file was created 0644.
  E5  an unknown --provider was not rejected: models.py silently returned the
      claude catalog, history.py an empty registry history. Two scripts, two
      different answers to the same wrong input.
"""
import json
import os
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import provider_secrets as ps  # noqa: E402
import sessions_registry  # noqa: E402

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _claude_stub(tmp_path, monkeypatch, body, exit_code=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    claude = bin_dir / "claude"
    claude.write_text("#!/bin/sh\nprintf '%s' '" + body + "'\nexit " + str(exit_code) + "\n")
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    return bin_dir


# --- E1: "no answer" and "answered: signed out" ---

def test_claude_signed_out_with_a_json_answer_is_not_signed_in(tmp_path, monkeypatch):
    _claude_stub(tmp_path, monkeypatch, '{"loggedIn": false}')
    assert ps.is_signed_in("claude") is False


def test_claude_signed_in_with_a_json_answer_is_signed_in(tmp_path, monkeypatch):
    _claude_stub(tmp_path, monkeypatch, '{"loggedIn": true}')
    assert ps.is_signed_in("claude") is True


def test_claude_that_cannot_answer_does_not_block(tmp_path, monkeypatch):
    """No answer at all — an old CLI, not on PATH, no network — must not stop
    the chat: the run itself decides."""
    _claude_stub(tmp_path, monkeypatch, "", exit_code=3)
    assert ps.is_signed_in("claude") is True


# --- E3: the lock file is not world-readable ---

def test_the_registry_lock_file_is_owner_only(tmp_path, monkeypatch):
    path = tmp_path / "sessions.json"
    monkeypatch.setattr(sessions_registry, "REGISTRY_PATH", str(path))
    sessions_registry.add("claude", "s1", "Заголовок", "/tmp")
    lock = path.with_suffix(".json.lock")
    if lock.exists():
        mode = stat.S_IMODE(os.stat(lock).st_mode)
        assert mode == 0o600, oct(mode)


# --- E5: an unknown provider is rejected ---

def _run_script(name, *args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, os.path.join(PLUGIN, name), *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def test_models_rejects_an_unknown_provider(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    out = _run_script("models.py", "--provider", "nonsense", env=env)
    assert out.returncode != 0, out.stdout
    assert "nonsense" in out.stderr, out.stderr


def test_history_rejects_an_unknown_provider(tmp_path):
    cwd = tmp_path / "work"
    cwd.mkdir()
    env = dict(os.environ, HOME=str(tmp_path))
    out = _run_script("history.py", "--provider", "nonsense", "list",
                      cwd=str(cwd), env=env)
    assert out.returncode != 0, out.stdout
    assert "nonsense" in out.stderr, out.stderr


def test_the_known_providers_still_work(tmp_path):
    cwd = tmp_path / "work"
    cwd.mkdir()
    env = dict(os.environ, HOME=str(tmp_path))
    for provider in ("claude", "cvc", "qoder", "kimi"):
        out = _run_script("history.py", "--provider", provider, "list",
                          cwd=str(cwd), env=env)
        assert out.returncode == 0, (provider, out.stderr)
