#!/usr/bin/env python3
"""Jarvis session registry — which sessions this chat owns, per provider.

Claude Code, Qoder and Kimi each keep their own transcripts in their own
format, and none of them can answer "sessions this chat started". The registry
records those ids here, so history.py can list exactly what Jarvis owns and
nothing else (a TUI session started by the user in the same directory stays
out of the plugin's history).

Shape: {provider: {sessionId: {title, workDir, ts}}} under
$XDG_STATE_HOME/dms-agent/sessions.json (default ~/.local/state/dms-agent;
a private state dir, already ignored by ccsync). XDG_STATE_HOME is honoured
so the test stand (jarvis-stand runs the shell with its own XDG_STATE_HOME)
keeps its own registry and cannot clobber the real one.

Writes go through an exclusive lock and land with an atomic replace: the two
DMS bars, the stand and the real shell may all write at once, and a lost
update here means a whole provider key silently disappears from history.
"""
import fcntl
import json
import os
import re
import tempfile
import time


def _registry_path():
    state_home = os.environ.get("XDG_STATE_HOME", "~/.local/state")
    return os.path.join(os.path.expanduser(state_home), "dms-agent", "sessions.json")


REGISTRY_PATH = _registry_path()

_TITLE_MAX = 200


def _load():
    try:
        with open(REGISTRY_PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    directory = os.path.dirname(REGISTRY_PATH)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".sessions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, REGISTRY_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _locked:
    """Exclusive lock around a read-modify-write cycle."""

    def __enter__(self):
        os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
        # The lock file is not a secret, but there is no reason to let another
        # user of the machine write to it.
        fd = os.open(REGISTRY_PATH + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
        self._fh = os.fdopen(fd, "w")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        return False


def _clean_title(title):
    return re.sub(r"\s+", " ", str(title or "")).strip()[:_TITLE_MAX]


def add(provider, session_id, title, work_dir):
    if not provider or not session_id:
        return
    entry = {
        "title": _clean_title(title),
        "workDir": str(work_dir or ""),
        "ts": time.time(),
    }
    with _locked():
        data = _load()
        data.setdefault(provider, {})[session_id] = entry
        _save(data)


def add_if_absent(provider, session_id, title, work_dir):
    """Remember the session unless it is remembered already; True once it is.

    Called after every message of providers whose transcripts cannot be
    scanned, so an existing entry keeps whatever title it has — a rename made
    in between must survive.
    """
    if not provider or not session_id:
        return False
    entry = {
        "title": _clean_title(title),
        "workDir": str(work_dir or ""),
        "ts": time.time(),
    }
    with _locked():
        data = _load()
        bucket = data.setdefault(provider, {})
        if session_id in bucket:
            return True
        bucket[session_id] = entry
        _save(data)
    return True


def rename(provider, session_id, title):
    with _locked():
        data = _load()
        entry = data.get(provider, {}).get(session_id)
        if entry is None:
            return
        entry["title"] = _clean_title(title)
        entry["ts"] = time.time()
        _save(data)


def remove(provider, session_id):
    with _locked():
        data = _load()
        if data.get(provider, {}).pop(session_id, None) is None:
            return
        if not data[provider]:
            data.pop(provider, None)
        _save(data)


def list(provider):
    """Newest first, the same order the history panel shows."""
    data = _load().get(provider, {})
    entries = []
    for sid, meta in data.items():
        if not isinstance(meta, dict):
            continue
        entries.append({
            "id": sid,
            "title": meta.get("title", ""),
            "workDir": meta.get("workDir", ""),
            "ts": meta.get("ts", 0),
        })
    entries.sort(key=lambda e: e["ts"], reverse=True)
    return entries
