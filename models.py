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
import time
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
# Registered providers (providers.json): their catalog source is their adapter.
import registry as _prov_registry  # noqa: E402

try:
    _registered = dict(_prov_registry.load().get("providers", {}))
except _prov_registry.RegistryError:
    _registered = {}
_registered_adapters = {pid: e.get("adapter") for pid, e in _registered.items()
                        if isinstance(e, dict)}
if provider not in KNOWN_PROVIDERS and provider not in _registered_adapters:
    print("models.py: unknown provider %r (known: %s)"
          % (provider, ", ".join(sorted(set(KNOWN_PROVIDERS) | set(_registered_adapters)))),
          file=sys.stderr)
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
# The same presets inside a gateway namespace: "9router/tk-free",
# "9router/tokenator-paid". The whole tk/ namespace is the Tokenator's, and
# "tk" alone is a path segment of it.
TOKENATOR_SEGMENTS = {"tk", "tokenator", "tokenator-paid"}


def claude_model_id(mid):
    if not mid:
        return False
    if mid in SKIP_IDS or mid in COMBO_IDS:
        return False
    if mid.startswith(SKIP_PREFIXES) or mid.startswith(GROUP_PREFIX):
        return False
    if mid.startswith(TOKENATOR_PREFIX):
        return False
    # The ban is on the preset, not on its spelling: a gateway namespaces the
    # same ids ("9router/claude-cowork-combo", "9router/tk-free",
    # "9router/tk/claude-opus-5"). So every path segment is checked, not only
    # the first one.
    for segment in str(mid).replace(":", "/").split("/"):
        if segment in COMBO_IDS or segment in TOKENATOR_SEGMENTS:
            return False
        if segment.startswith(TOKENATOR_PREFIX) and segment != "tk":
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


# --- Registry providers (adapters codex / openai / acp) ---------------------

def parse_codex_debug(text):
    """`codex debug models` output -> a list of model rows.

    codex-cli 0.166.0 prints a single JSON object {"models": [...]}; older
    line-per-model output is still accepted so a CLI update cannot silently
    break the catalog."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        return data["models"]
    # Legacy/other shapes: one JSON object per line.
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def map_codex_models(rows):
    """codex debug models rows -> the plugin's model list.

    visibility "hide" is the CLI saying "not selectable" — dropped here, not
    shown-and-hoped. The common filter (Combo/Tokenator/fable/default) applies
    to everything."""
    out = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        mid = m.get("slug") or m.get("id") or ""
        if not mid or m.get("visibility") == "hide":
            continue
        if not claude_model_id(mid):
            continue
        out.append({
            "id": mid,
            "label": m.get("display_name") or m.get("name") or mid,
            "resolved": mid,
            "desc": m.get("description", ""),
            "efforts": [l.get("effort") for l in m.get("supported_reasoning_levels") or []
                        if isinstance(l, dict) and l.get("effort")],
        })
    return out


def ask_codex():
    out = subprocess.run(["codex", "debug", "models"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "codex debug models failed")
    return out.stdout


def map_openai_models(payload, base_url):
    """Gateway /models (OpenAI style) -> the plugin's model list.

    The catalog says nothing about reasoning support, so no effort chip is
    offered: claiming levels the gateway never asked for would be a guess."""
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
        if not mid or not claude_model_id(mid):
            continue
        out.append({
            "id": mid,
            "label": m.get("display_name") or m.get("owned_by") or mid,
            "resolved": mid,
            "desc": m.get("owned_by") or "",
            "efforts": [],
        })
    return out


def ask_openai(pid):
    entry = _registered.get(pid) or {}
    base = (entry.get("baseUrl") or "").rstrip("/")
    if not base:
        raise RuntimeError("provider %r has no baseUrl" % pid)
    import urllib.request
    key = provider_secrets.get_api_key(pid)
    req = urllib.request.Request(base + "/models")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(req, timeout=30) as resp:
        return json.load(resp)


def ask_acp_models(command):
    """The model catalog of an ACP agent -> the plugin's model list.

    The agent's own list comes with its session (models.availableModels or
    configOptions with category "model"); asking for it costs no model call:
    initialize + session/new only, then the process is stopped.
    """
    args = list(command or [])
    if not args:
        raise RuntimeError("provider has no command")
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    rows = []
    try:
        def send(obj):
            try:
                proc.stdin.write(json.dumps(obj) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise RuntimeError("the agent closed its input: %s" % e)

        def read_for(rid, timeout=60):
            import select as _select
            buf = ""
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ready, _, _ = _select.select([proc.stdout], [], [], 0.5)
                if not ready:
                    continue
                line = proc.stdout.readline()
                if not line:
                    break
                buf += line
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("id") == rid:
                    return msg.get("result") or {}
            return {}

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": 1, "clientCapabilities": {"fs": {}}}})
        read_for(1)
        send({"jsonrpc": "2.0", "id": 2, "method": "session/new",
              "params": {"cwd": os.getcwd(), "mcpServers": []}})
        result = read_for(2)
        if not isinstance(result, dict) or not (result.get("models") or
                                                result.get("configOptions")):
            raise RuntimeError("the agent did not return a model catalog")
        rows = map_acp_models(result)
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return rows


def map_acp_models(result):
    """An ACP session/new result -> the plugin's model list.

    Two shapes exist: models.availableModels (gemini-cli 0.66) and the
    configOptions entries with category "model". Both are read; the agent
    decides which it sends.
    """
    out = []
    seen = set()
    models = result.get("models") if isinstance(result, dict) else None
    if isinstance(models, dict):
        for row in models.get("availableModels") or []:
            if not isinstance(row, dict):
                continue
            mid = row.get("modelId") or row.get("id") or row.get("value")
            if not mid or mid in seen or not claude_model_id(mid):
                continue
            seen.add(mid)
            out.append({"id": mid, "label": row.get("name") or row.get("title") or mid,
                        "resolved": mid, "desc": row.get("description") or "",
                        "efforts": []})
    for opt in (result.get("configOptions") or []) if isinstance(result, dict) else []:
        if not isinstance(opt, dict) or opt.get("category") != "model":
            continue
        for entry in opt.get("options") or []:
            if not isinstance(entry, dict):
                continue
            mid = entry.get("value")
            if not mid or mid in seen or not claude_model_id(mid):
                continue
            seen.add(mid)
            out.append({"id": mid, "label": entry.get("name") or mid,
                        "resolved": mid, "desc": "", "efforts": []})
    return out


def fetch_models_for(provider):
    if provider == "cvc":
        return map_cvc_models(ask_cvc())
    if provider == "qoder":
        return map_qoder_models(ask_qoder())
    if provider == "kimi":
        return map_kimi_models(ask_kimi())
    adapter = _registered_adapters.get(provider)
    if provider not in KNOWN_PROVIDERS and adapter is None:
        raise RuntimeError("unknown provider %r" % provider)
    if adapter == "codex":
        return map_codex_models(parse_codex_debug(ask_codex()))
    if adapter == "openai":
        return map_openai_models(ask_openai(provider), _registered[provider].get("baseUrl", ""))
    if adapter == "acp":
        # The agent's own catalog arrives over the ACP session: it is the
        # session/new answer (models.availableModels or the configOptions of
        # category "model"). Asking for it costs no model call.
        entry = _registered.get(provider) or {}
        command = entry.get("command") or []
        if isinstance(command, str):
            command = command.split()
        return ask_acp_models(command)
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
