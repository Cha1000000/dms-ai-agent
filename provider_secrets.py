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
import sys
import urllib.request

CVC_BASE_URL = "https://ru.cheapvibecode.ru"
# The local gateway of the cc9 wrapper (see ~/.local/bin/cc9).
CC9_ROUTER_URL = "http://127.0.0.1:20128"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry  # noqa: E402


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect carrying the Authorization header.

    urllib copies request headers into the redirected request, so a 30x from
    the gateway would send the user's key to whatever origin (or plain-HTTP
    address) the Location names. The same rule is pinned for the OpenAI
    gateway in models.py and test_security_contract.py."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cvc_models(timeout=15):
    """GET /v1/models with the stored key; raises on any failure."""
    key = get_api_key("cvc")
    if not key:
        raise RuntimeError("no api key")
    req = urllib.request.Request(
        CVC_BASE_URL + "/v1/models",
        headers={"Authorization": "Bearer " + key},
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(req, timeout=timeout) as resp:
        return json.load(resp)


def get_api_key(provider):
    return registry.get_key(provider)


def set_api_key(provider, key):
    if not provider:
        return
    registry.set_key(provider, key)


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
    env = export_env(provider)
    if provider == "cvc" and not env:
        # Providers.js builds `eval $(...) && claude ...`. An empty prefix
        # would let the stock CLI run on the user's own Anthropic login — a
        # silent switch of backend. `false` makes the `&&` chain stop.
        return "false; "
    return "".join(
        "export %s=%s; " % (name, shlex.quote(value))
        for name, value in env.items()
    )


def test_cvc_key():
    """Short GET /v1/models with the stored key. Returns "ok <n>" | "missing" | "fail: ..."."""
    if not get_api_key("cvc"):
        return "missing"
    try:
        payload = cvc_models()
        rows = payload.get("data") if isinstance(payload, dict) else None
        return "ok %d" % (len(rows) if isinstance(rows, list) else 0)
    except Exception as e:
        return "fail: %s" % e


def cc9_ready():
    """Whether the cc9 provider may run: the wrapper is on PATH AND the 9Router
    gateway answers. The wrapper's own fallback launches Tokenator when the
    gateway is down — forbidden in Jarvis ("Никаких Комбо и моделей Токенатора
    в Джарвисе быть не должно") — so a down gateway is a hard "no": the launch
    is blocked here instead of being left to the wrapper's discretion. There is
    an unavoidable race (the gateway can die between this check and exec); the
    check closes the common case, the wrapper's fallback can still fire after
    an in-flight outage."""
    if not shutil.which("cc9"):
        return False
    try:
        import urllib.request
        req = urllib.request.Request(CC9_ROUTER_URL + "/api/version")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except Exception:
        # Gateway down: run would fall through to the wrapper's Tokenator
        # fallback — refuse rather than launch it.
        return False


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
        if not isinstance(data, dict):
            # JSON that is not an object says nothing about the login.
            return True
        # An answer that says nothing about the login is a definite "no":
        # the chat must point at the login command instead of failing with a
        # wall of auth errors.
        return bool(data.get("loggedIn"))
    # A provider from providers.json: its adapter decides what "signed in"
    # means. ACP has no cheap probe (starting the agent just to ask costs a
    # process and may prompt), so it stays unknown-but-allowed; Codex and an
    # OpenAI gateway are explicit.
    try:
        entry = registry.load().get("providers", {}).get(provider)
    except registry.RegistryError:
        entry = None
    if isinstance(entry, dict):
        adapter = entry.get("adapter")
        if adapter == "openai":
            return bool(get_api_key(provider))
        if adapter == "codex":
            import subprocess
            try:
                out = subprocess.run(["codex", "login", "status"],
                                     capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.SubprocessError):
                return True  # no answer — let the run decide
            # codex-cli 0.167 prints "Not logged in" with exit status 0.
            return "not logged in" not in (out.stdout + out.stderr).lower()
        return True
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
