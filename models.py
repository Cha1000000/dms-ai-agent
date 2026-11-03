#!/usr/bin/env python3
"""Print the model list a provider offers, as JSON.

For claude the list comes from the CLI itself (the "initialize" control request
of the stream-json protocol), so new versions and names show up without touching
the plugin. CheapVibeCode is the same CLI on another gateway, but that gateway
has its own catalog (44 models, not only Claude) served at GET /v1/models —
mapped here. Other providers have their own source (an HTTP endpoint, a config
file, a CLI flag) — each is added here when its adapter lands. The result is
cached per provider; if the source can't be reached, the cache is printed.

Output: [{"id": "opus", "label": "Opus 5.5", "resolved": "claude-opus-5-5",
          "desc": "...", "efforts": ["low", "medium", ...]}, ...]
"efforts" is empty for models that don't support the effort setting.
"""
import json
import os
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider_secrets  # noqa: E402

argv = sys.argv[1:]
provider = "claude"
if argv and argv[0].startswith("--provider="):
    provider = argv[0].split("=", 1)[1]
    argv = argv[1:]
elif "--provider" in argv:
    i = argv.index("--provider")
    provider = argv[i + 1] if i + 1 < len(argv) else "claude"
    del argv[i:i + 2]
# The known providers. An unknown one is rejected: answering with the claude
# catalog would be a wrong answer with a confident face.
KNOWN_PROVIDERS = ("claude", "cvc", "cc9", "qoder", "kimi")
if provider not in KNOWN_PROVIDERS:
    print("models.py: unknown provider %r (known: %s)"
          % (provider, ", ".join(KNOWN_PROVIDERS)), file=sys.stderr)
    sys.exit(2)

CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                     "dms-agent", "models-%s.json" % provider)
# "default" just duplicates one of the entries; Fable is left out on purpose.
SKIP_IDS = {"default"}
SKIP_PREFIXES = ("fable", "claude-fable")
# When the claude CLI is a harness wrapper (cc9 + 9Router), its catalog is a
# gateway aggregate: section headers ("cc9-group:*"), the Combo presets and
# the Tokenator namespace are not models and must not reach the picker
# ("Никаких Комбо и моделей Токенатора в Джарвисе быть не должно"). Every
# other id of the aggregate IS a model of the harness the user runs — the one
# their --model takes — so they stay. Caught live 2026-11-03: the filter used
# to drop every id with a slash, and the picker was left with three aliases
# while the harness offered 181 models.
COMBO_IDS = {"claude-cowork-combo", "free-models", "tk-free", "tokenator-paid"}
GROUP_PREFIX = "cc9-group:"
# tk/ is the Tokenator namespace of the 9Router.
TOKENATOR_PREFIX = "tk/"


def claude_model_id(mid):
    if not mid:
        return False
    if mid in SKIP_IDS or mid in COMBO_IDS:
        return False
    if mid.startswith(SKIP_PREFIXES) or mid.startswith(GROUP_PREFIX):
        return False
    if mid.startswith(TOKENATOR_PREFIX):
        return False
    # Fable stays out of the picker, wherever it comes from (the native catalog
    # and the gateways' namespaces alike).
    return "fable" not in mid


# The bare --model aliases of Claude Code. A harness wrapper's catalog may not
# list them (it routes them through its own presets), but the CLI still accepts
# them, and the provider is built around them.
CLAUDE_ALIASES = [
    {"id": "opus", "label": "Opus", "resolved": "opus",
     "desc": "Claude Code", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"id": "sonnet", "label": "Sonnet", "resolved": "sonnet",
     "desc": "Claude Code", "efforts": ["low", "medium", "high", "xhigh", "max"]},
    {"id": "haiku", "label": "Haiku", "resolved": "haiku",
     "desc": "Claude Code", "efforts": ["low", "medium", "high", "xhigh", "max"]},
]


def with_claude_aliases(models):
    """Add the bare "opus"/"sonnet"/"haiku" aliases to a native catalog.

    A harness aggregate (cc9 + 9Router) gets none: there the aliases are its
    own presets, and they resolve to the Combo — which must not be in Jarvis.
    """
    if any("/" in m["id"] for m in models):
        return models
    have = {m["id"] for m in models}
    return models + [m for m in CLAUDE_ALIASES if m["id"] not in have]
# Same set the Claude Code CLI exposes as --effort; the CVC gateway forwards it
# for models that can reason.
CVC_EFFORTS = ["low", "medium", "high", "xhigh", "max"]
# qodercli --reasoning-effort takes auto, none, low, medium, high, xhigh, max,
# ultracode. "auto" is the empty chip (no flag at all) and "none" turns
# reasoning off rather than tuning it, so the picker offers the rest.
QODER_EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultracode"]


def ask_cli(cli="claude"):
    request = json.dumps({"type": "control_request", "request_id": "models",
                          "request": {"subtype": "initialize"}})
    # No hooks, no MCP servers, no session file: only the model list is needed.
    out = subprocess.run(
        [cli, "-p", "--no-session-persistence", "--strict-mcp-config",
         "--settings", '{"disableAllHooks":true}',
         "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"],
        input=request + "\n", capture_output=True, text=True, timeout=60,
    ).stdout
    for line in out.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("type") == "control_response":
            return msg["response"]["response"]["models"]
    raise RuntimeError("no control_response")


def map_cvc_models(payload):
    """Gateway /v1/models (OpenAI-style) -> the plugin's model list."""
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    out = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        if not mid or mid in SKIP_IDS or str(mid).startswith(SKIP_PREFIXES):
            continue
        if "fable" in str(mid):
            continue
        out.append({
            "id": mid,
            "label": m.get("display_name") or mid,
            # The gateway rejects bare aliases — always pass the full id.
            "resolved": mid,
            "desc": m.get("series") or "",
            "efforts": list(CVC_EFFORTS) if m.get("supports_reasoning") else [],
        })
    return out


def ask_cvc():
    key = provider_secrets.get_api_key("cvc")
    if not key:
        raise RuntimeError("no api key")
    req = urllib.request.Request(
        provider_secrets.CVC_BASE_URL + "/v1/models",
        headers={"Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def map_qoder_models(text):
    """`qodercli --list-models` -> the plugin's model list.

    The CLI prints one bare id per line under a "MODEL" header and no
    metadata, so every model is offered with the full effort enum."""
    out = []
    for line in (text or "").splitlines():
        mid = line.strip()
        if not mid or mid == "MODEL":
            continue
        out.append({
            "id": mid,
            "label": mid,
            "resolved": mid,
            "desc": "",
            "efforts": list(QODER_EFFORTS),
        })
    return out


def ask_qoder():
    out = subprocess.run(["qodercli", "--list-models"],
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "qodercli --list-models failed")
    return out.stdout


def map_kimi_models(text):
    """~/.kimi-code/config.toml -> the plugin's model list.

    The CLI owns that file (it also holds the login), so it is only read. Each
    [models."provider/alias"] key is exactly what -m takes — a bare "k3" is
    rejected — and support_efforts is the effort chip; a model that has no such
    list gets no chip at all."""
    if not text:
        return []
    try:
        import tomllib
        data = tomllib.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    for mid, meta in (data.get("models") or {}).items():
        if not isinstance(meta, dict):
            continue
        out.append({
            "id": mid,
            "label": meta.get("display_name") or mid,
            "resolved": mid,
            "desc": "",
            "efforts": list(meta.get("support_efforts") or []),
        })
    return out


def ask_kimi():
    with open(os.path.expanduser("~/.kimi-code/config.toml")) as f:
        return f.read()


def fetch_models_for(provider):
    if provider == "cvc":
        return map_cvc_models(ask_cvc())
    if provider == "qoder":
        return map_qoder_models(ask_qoder())
    if provider == "kimi":
        return map_kimi_models(ask_kimi())
    if provider == "cc9":
        # The wrapper's catalog — the gateway's aggregate, not the native
        # Claude one. The bare aliases are not added: in that catalog they are
        # the wrapper's own presets and resolve to the Combo.
        return [
            {"id": m["value"], "label": m.get("displayName") or m["value"],
             "resolved": m.get("resolvedModel", m["value"]),
             "desc": m.get("description", ""),
             "efforts": m.get("supportedEffortLevels") or []}
            for m in ask_cli("cc9")
            if claude_model_id(m["value"])
        ]
    return with_claude_aliases([
        {"id": m["value"], "label": m.get("displayName") or m["value"],
         "resolved": m.get("resolvedModel", m["value"]), "desc": m.get("description", ""),
         "efforts": m.get("supportedEffortLevels") or []}
        for m in ask_cli()
        if claude_model_id(m["value"])
    ])


def fetch_models():
    return fetch_models_for(provider)


def main():
    try:
        models = fetch_models()
        if not models:
            raise RuntimeError("empty model list")
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as f:
            json.dump(models, f)
    except Exception as e:
        print(f"models.py: {e}", file=sys.stderr)
        try:
            with open(CACHE) as f:
                models = json.load(f)
        except (OSError, ValueError):
            sys.exit(1)
    print(json.dumps(models, ensure_ascii=False))


if __name__ == "__main__":
    main()
