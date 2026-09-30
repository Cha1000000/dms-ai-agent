#!/usr/bin/env python3
"""Print the model list the Claude Code CLI offers in /model, as JSON.

The list comes from the CLI itself (the "initialize" control request of the
stream-json protocol), so new versions and names show up without touching the
plugin. The result is cached; if the CLI can't be asked, the cache is printed.

Output: [{"id": "opus", "label": "Opus 5.5", "resolved": "claude-opus-5-5",
          "desc": "..."}, ...]
"""
import json
import os
import subprocess
import sys

CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                     "dms-agent", "models.json")
# "default" just duplicates one of the entries; Fable is left out on purpose.
SKIP_IDS = {"default"}
SKIP_PREFIXES = ("fable", "claude-fable")


def ask_cli():
    request = json.dumps({"type": "control_request", "request_id": "models",
                          "request": {"subtype": "initialize"}})
    # No hooks, no MCP servers, no session file: only the model list is needed.
    out = subprocess.run(
        ["claude", "-p", "--no-session-persistence", "--strict-mcp-config",
         "--settings", '{"disableAllHooks":true}',
         "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"],
        input=request + "\n", capture_output=True, text=True, timeout=30,
    ).stdout
    for line in out.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("type") == "control_response":
            return msg["response"]["response"]["models"]
    raise RuntimeError("no control_response")


def main():
    try:
        models = [
            {"id": m["value"], "label": m.get("displayName") or m["value"],
             "resolved": m.get("resolvedModel", m["value"]), "desc": m.get("description", "")}
            for m in ask_cli()
            if m["value"] not in SKIP_IDS and not m["value"].startswith(SKIP_PREFIXES)
        ]
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
