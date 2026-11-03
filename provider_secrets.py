#!/usr/bin/env python3
"""Provider credentials for DMS Agent.

Keys live in ~/.local/state/dms-agent/providers.json (0600) — a private state
dir, deliberately not in plugin_settings.json, which ccsync syncs between
machines. Shape: {"cvc": {"apiKey": "sk-..."}}.

Also builds the environment a provider's CLI needs (CheapVibeCode is the stock
claude CLI pointed at their gateway).
"""
import json
import os
import shutil
import stat
import sys

STORE_PATH = os.path.join(
    os.path.expanduser("~/.local/state/dms-agent"), "providers.json"
)
# The store path can be pointed elsewhere (the test stand, a throwaway copy).
# It is not a secret itself — the key inside it is.
if os.environ.get("PROVIDER_SECRETS_STORE"):
    STORE_PATH = os.environ["PROVIDER_SECRETS_STORE"]
CVC_BASE_URL = "https://ru.cheapvibecode.ru"
# The local gateway of the cc9 wrapper (see ~/.local/bin/cc9).
CC9_ROUTER_URL = "http://localhost:20128"


def _load():
    try:
        with open(STORE_PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    # Created with the mode already set: writing first and chmod-ing after
    # leaves a window in which the key is world-readable, and a crash in that
    # window leaves it that way for good.
    fd = os.open(STORE_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.chmod(STORE_PATH, stat.S_IRUSR | stat.S_IWUSR)


def get_api_key(provider):
    entry = _load().get(provider) or {}
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("apiKey") or "")


def set_api_key(provider, key):
    if not provider:
        return
    data = _load()
    key = (key or "").strip()
    if not key:
        data.pop(provider, None)
    else:
        data[provider] = {"apiKey": key}
    if data:
        _save(data)
    elif os.path.exists(STORE_PATH):
        os.remove(STORE_PATH)


def export_env(provider):
    """Environment variables the provider's CLI needs, given the stored key."""
    key = get_api_key(provider)
    if not key:
        return {}
    if provider == "cvc":
        return {
            "ANTHROPIC_BASE_URL": CVC_BASE_URL,
            "ANTHROPIC_AUTH_TOKEN": key,
        }
    return {}


def env_export_shell(provider):
    """Shell `export` lines for `eval $(...)`; empty when there is no key."""
    import shlex
    return "".join(
        "export %s=%s; " % (name, shlex.quote(value))
        for name, value in export_env(provider).items()
    )


def test_cvc_key():
    """Short GET /v1/models with the stored key. Returns "ok <n>" | "missing" | "fail: ..."."""
    import urllib.request
    key = get_api_key("cvc")
    if not key:
        return "missing"
    req = urllib.request.Request(
        CVC_BASE_URL + "/v1/models",
        headers={"Authorization": "Bearer " + key},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.load(resp)
        rows = payload.get("data") if isinstance(payload, dict) else None
        return "ok %d" % (len(rows) if isinstance(rows, list) else 0)
    except Exception as e:
        return "fail: %s" % e


def cc9_ready():
    """Whether the cc9 wrapper can run: the wrapper is on PATH and the 9Router
    gateway answers. The wrapper falls back to Tokenator on its own when the
    gateway is down, so a down gateway is not a hard "no" — but without the
    wrapper there is nothing to run at all."""
    if not shutil.which("cc9"):
        return False
    try:
        import urllib.request
        req = urllib.request.Request(CC9_ROUTER_URL + "/api/version")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except Exception:
        # The gateway is down: the wrapper falls back to Tokenator, so the
        # provider is still usable.
        return True


def is_signed_in(provider):
    """Whether the provider can run at all: the key store has a key, or the
    CLI has a login. A probe that cannot tell counts as signed in — only a
    definite "no credentials" stops the chat and points at the login command."""
    if provider == "cvc":
        return bool(get_api_key("cvc"))
    if provider == "cc9":
        return cc9_ready()
    if provider == "kimi":
        import glob
        return bool(glob.glob(os.path.expanduser("~/.kimi-code/credentials/*.json")))
    if provider == "qoder":
        return os.path.isfile(os.path.expanduser("~/.qoder/credentials/auth.json"))
    if provider == "claude":
        import subprocess
        try:
            out = subprocess.run(["claude", "auth", "status"],
                                 capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return True  # no answer, an old CLI, not on PATH — let the run decide
        try:
            data = json.loads(out.stdout)
        except ValueError:
            # Not an answer, so no answer at all: an old CLI, a wrapper, a
            # different locale. The run itself decides.
            return True
        # An answer that says nothing about the login is a definite "no":
        # the chat must point at the login command instead of failing with a
        # wall of auth errors.
        return bool(data.get("loggedIn"))
    return True


def main():
    argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "get":
        sys.stdout.write(get_api_key(argv[1]))
    elif len(argv) >= 2 and argv[0] == "set":
        # The key comes from stdin, not from argv: a command line is visible to
        # every user of the machine in /proc/<pid>/cmdline, and this is a
        # secret. The argv form is kept as a fallback for a caller that has no
        # stdin to give.
        #
        # "No key at all" and "an empty key" are different: the first is a
        # caller with nothing to say (the stored key stays), the second is an
        # explicit request to forget it. An empty readline means the stream
        # ended; a bare newline means the caller typed an empty key.
        key = None
        if not sys.stdin.isatty():
            line = sys.stdin.readline()
            if line != "":
                key = line.strip()
        if key is None and len(argv) >= 3:
            key = argv[2]
        if not argv[1] or key is None:
            print("ok" if argv[1] else "fail")
            sys.exit(0 if argv[1] else 2)
        set_api_key(argv[1], key)
        print("ok" if get_api_key(argv[1]) or not key else "fail")
    elif len(argv) >= 2 and argv[0] == "env":
        print(json.dumps(export_env(argv[1]), ensure_ascii=False))
    elif len(argv) >= 2 and argv[0] == "env-export":
        sys.stdout.write(env_export_shell(argv[1]))
    elif len(argv) >= 2 and argv[0] == "check":
        print("set" if is_signed_in(argv[1]) else "missing")
    elif len(argv) >= 2 and argv[0] == "test" and argv[1] == "cvc":
        print(test_cvc_key())
    else:
        print("usage: provider_secrets.py get|set|env|env-export|check|test <provider> [key]",
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
