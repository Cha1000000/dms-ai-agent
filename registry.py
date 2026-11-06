#!/usr/bin/env python3
"""Provider registry for DMS Agent — the single store for providers and keys.

One file, $XDG_STATE_HOME/dms-agent/providers.json (0600), two sections:

    {"version": 1,
     "providers": {"<id>": {...descriptor...}},
     "keys":      {"<id>": {"apiKey": "..."}}}

The file path honours XDG_STATE_HOME (the test stand runs with its own state
dir) and PROVIDER_REGISTRY (an explicit test override that wins over XDG).
provider_secrets.py reads its keys through this module, so both scripts always
point at the same file and one migration covers both.

Reads never rewrite the file — a corrupt or unknown-version file raises
RegistryError instead of being silently replaced by an empty store (that would
be how a parallel writer's settings or a real API key vanish).
"""
import fcntl
import json
import os
import re
import stat
import sys
import tempfile

ID_RE = re.compile(r"^[a-z0-9-]+$")
KNOWN_ADAPTERS = ("claude", "acp", "codex", "openai")
VERSION = 1


class RegistryError(Exception):
    """The store cannot be read or written; the caller must not retry blindly."""


class ValidationError(RegistryError):
    """A provider entry does not pass validation."""


def _registry_path():
    override = os.environ.get("PROVIDER_REGISTRY")
    if override:
        return override
    state_home = os.environ.get("XDG_STATE_HOME", "~/.local/state")
    return os.path.join(os.path.expanduser(state_home), "dms-agent", "providers.json")


REGISTRY_PATH = _registry_path()


def _empty():
    return {"version": VERSION, "providers": {}, "keys": {}}


def _migrate(raw):
    """Old flat {"cvc": {"apiKey": ...}} -> the versioned shape, in memory."""
    if not isinstance(raw, dict):
        raise RegistryError("registry is not a JSON object")
    if "version" in raw:
        if raw["version"] != VERSION:
            raise RegistryError("registry version %r is not supported" % (raw["version"],))
        providers = raw.get("providers")
        keys = raw.get("keys")
        if not isinstance(providers, dict) or not isinstance(keys, dict):
            raise RegistryError("registry sections are malformed")
        return {"version": VERSION, "providers": providers, "keys": keys}
    # Legacy flat store: {"cvc": {"apiKey": ...}} — provider ids as top-level
    # keys with apiKey payloads. Values that look like key entries migrate to
    # `keys`; anything else is an unknown shape worth reporting, not swallowing.
    keys = {}
    for pid, entry in raw.items():
        if isinstance(entry, dict) and set(entry) <= {"apiKey"}:
            keys[pid] = entry
        else:
            raise RegistryError("registry has unknown sections: %s" % ", ".join(sorted(raw)))
    return {"version": VERSION, "providers": {}, "keys": keys}


def _validate_pid(pid):
    if not ID_RE.match(str(pid)) or "/" in str(pid) or ".." in str(pid):
        raise ValidationError("bad provider id %r: must match %s" % (pid, ID_RE.pattern))


def validate_entry(pid, entry):
    _validate_pid(pid)
    if not isinstance(entry, dict):
        raise ValidationError("provider %r: entry must be an object" % (pid,))
    adapter = entry.get("adapter")
    if adapter not in KNOWN_ADAPTERS:
        raise ValidationError(
            "provider %r: unknown adapter %r (known: %s)"
            % (pid, adapter, ", ".join(KNOWN_ADAPTERS))
        )


def _locked_load():
    """Load under the exclusive lock; for read-modify-write cycles."""
    directory = os.path.dirname(REGISTRY_PATH)
    os.makedirs(directory, exist_ok=True)
    fd = os.open(REGISTRY_PATH + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            return _read_unlocked()
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _read_unlocked():
    try:
        with open(REGISTRY_PATH) as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return _empty()
    except ValueError as e:
        raise RegistryError("registry file is corrupt: %s" % e)
    except OSError as e:
        raise RegistryError("registry file is unreadable: %s" % e)
    return _migrate(raw)


def load():
    """Read the registry (with legacy migration in memory). Never writes."""
    if not os.path.exists(REGISTRY_PATH):
        return _empty()
    # A plain read does not need the lock: os.replace is atomic, so a reader
    # sees either the old or the new file, never a half-written one.
    return _read_unlocked()


def _save_locked(data):
    directory = os.path.dirname(REGISTRY_PATH)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".providers-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, REGISTRY_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _update(fn):
    """Read-modify-write under the lock. fn(data) -> data (mutated or new)."""
    with _locked() as _lock_ctx:
        data = _read_unlocked()
        result = fn(data)
        _save_locked(result)
        return result


class _locked:
    """Context manager holding the lock file open for the whole update."""

    def __enter__(self):
        directory = os.path.dirname(REGISTRY_PATH)
        os.makedirs(directory, exist_ok=True)
        fd = os.open(REGISTRY_PATH + ".lock", os.O_WRONLY | os.O_CREAT, 0o600)
        self._fh = os.fdopen(fd, "w")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        return False


def set_provider(pid, entry):
    validate_entry(pid, entry)

    def fn(data):
        data["providers"][pid] = entry
        return data

    return _update(fn)


def remove_provider(pid):
    _validate_pid(pid)

    with _locked() as _lock_ctx:
        data = _read_unlocked()
        existed = pid in data["providers"]
        data["providers"].pop(pid, None)
        if existed:
            _save_locked(data)
        return existed


def get_key(pid):
    entry = load().get("keys", {}).get(pid)
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("apiKey") or "")


def set_key(pid, key):
    _validate_pid(pid)
    key = str(key or "").strip()

    def fn(data):
        if key:
            data["keys"][pid] = {"apiKey": key}
        else:
            data["keys"].pop(pid, None)
        return data

    return _update(fn)


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "list" and "--json" in argv:
        # For QML: providers only. The keys never travel to the UI — they are
        # managed through provider_secrets.py and shown nowhere.
        data = load()
        print(json.dumps({"version": data["version"], "providers": data["providers"]},
                         ensure_ascii=False))
        return
    if argv and argv[0] == "set-provider" and len(argv) >= 2:
        # Entry JSON comes from stdin (the UI), never from argv: a command line
        # is readable in /proc/<pid>/cmdline and command strings are long.
        pid = argv[1]
        raw = sys.stdin.read()
        try:
            entry = json.loads(raw)
        except ValueError as e:
            print("invalid entry JSON: %s" % e, file=sys.stderr)
            sys.exit(2)
        try:
            set_provider(pid, entry)
        except RegistryError as e:
            print(str(e), file=sys.stderr)
            sys.exit(2)
        print("ok")
        return
    if argv and argv[0] == "remove-provider" and len(argv) >= 2:
        try:
            existed = remove_provider(argv[1])
        except RegistryError as e:
            print(str(e), file=sys.stderr)
            sys.exit(2)
        print("removed" if existed else "absent")
        return
    if argv and argv[0] == "set-key" and len(argv) >= 2:
        pid = argv[1]
        key = None
        if not sys.stdin.isatty():
            line = sys.stdin.readline()
            if line != "":
                key = line.strip()
        set_key(pid, key or "")
        print("ok")
        return
    print("usage: registry.py list --json | set-provider <id> (entry JSON from stdin)\n"
          "                | remove-provider <id> | set-key <provider> [key from stdin]",
          file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
