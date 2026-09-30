#!/usr/bin/env python3
"""List Claude Code sessions as JSON for DMS Agent history."""
import json, os, glob, re, sys

action = sys.argv[1] if len(sys.argv) > 1 else "list"
# The agent runs `claude -p` from the shell's working directory, and Claude Code
# stores sessions under a slug of that directory (non-alphanumerics -> "-").
# This script is launched the same way, so its cwd is the same directory.
base = os.path.join(os.path.expanduser("~/.claude/projects"), re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())) + "/"


def is_agent_session(path):
    """Agent sessions come from `claude -p` (entrypoint "sdk-cli"); interactive
    Claude Code sessions started in the same directory are left out."""
    with open(path) as fh:
        for i, line in enumerate(fh):
            if i > 50:
                break
            if '"entrypoint"' not in line:
                continue
            try:
                return json.loads(line).get("entrypoint") == "sdk-cli"
            except ValueError:
                continue
    return False


def custom_title(path):
    """The name given with /rename in the CLI or from this plugin: Claude Code
    keeps it as "custom-title" records in the transcript, the last one wins."""
    name = ""
    with open(path) as fh:
        for line in fh:
            if '"custom-title"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "custom-title":
                name = d.get("customTitle") or ""
    return name.strip()


if action == "list":
    results = []
    files = sorted(glob.glob(base + "*.jsonl"), key=os.path.getmtime, reverse=True)
    for f in [f for f in files if is_agent_session(f)][:20]:
        sid = os.path.basename(f).replace(".jsonl", "")
        mtime = os.path.getmtime(f)
        title = ""
        with open(f) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                    if d.get("type") == "user" and not d.get("isMeta"):
                        content = d.get("message", {}).get("content", "")
                        if isinstance(content, str) and not content.startswith("<"):
                            title = content[:60].replace("\n", " ")
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text" and not c["text"].startswith("<"):
                                    title = c["text"][:60].replace("\n", " ")
                                    break
                        if title:
                            break
                except:
                    pass
        if title:
            results.append({"id": sid, "title": custom_title(f) or title, "date": int(mtime * 1000)})
    print(json.dumps(results))

elif action == "delete":
    # Only ever removes agent sessions: an interactive Claude Code session
    # started in the same directory must survive, and the id arrives from the
    # outside, so it is checked rather than trusted.
    sid = sys.argv[2] if len(sys.argv) > 2 else ""
    ok = False
    if sid and "/" not in sid and ".." not in sid:
        path = base + sid + ".jsonl"
        if os.path.isfile(path) and is_agent_session(path):
            os.remove(path)
            ok = True
    print(json.dumps({"deleted": 1 if ok else 0}))

elif action == "rename":
    # Same records /rename writes, so the new name also shows up in the CLI's
    # /resume. An empty name drops back to the automatic title. Checked like
    # delete: the id and the name arrive from the outside.
    sid = sys.argv[2] if len(sys.argv) > 2 else ""
    name = " ".join((sys.argv[3] if len(sys.argv) > 3 else "").split())[:100]
    ok = False
    if sid and "/" not in sid and ".." not in sid:
        path = base + sid + ".jsonl"
        if os.path.isfile(path) and is_agent_session(path):
            with open(path, "rb+") as fh:
                fh.seek(0, os.SEEK_END)
                needs_newline = False
                if fh.tell() > 0:
                    fh.seek(-1, os.SEEK_END)
                    needs_newline = fh.read(1) != b"\n"
                records = [{"type": "custom-title", "customTitle": name, "sessionId": sid},
                           {"type": "agent-name", "agentName": name, "sessionId": sid}]
                # Compact, like the CLI writes it: it reads the title with a regex.
                data = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in records)
                fh.write((b"\n" if needs_newline else b"") + data.encode("utf-8"))
            ok = True
    print(json.dumps({"renamed": 1 if ok else 0}))

elif action == "delete-all":
    removed = 0
    for f in glob.glob(base + "*.jsonl"):
        if is_agent_session(f):
            try:
                os.remove(f)
                removed += 1
            except OSError:
                pass
    print(json.dumps({"deleted": removed}))

elif action == "restore":
    sid = sys.argv[2] if len(sys.argv) > 2 else ""
    session_file = base + sid + ".jsonl"
    msgs = []
    if os.path.exists(session_file):
        with open(session_file) as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get("type") == "user" and not d.get("isMeta"):
                        content = d.get("message", {}).get("content", "")
                        if isinstance(content, str) and not content.startswith("<"):
                            msgs.append({"role": "user", "content": content})
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text" and not c["text"].startswith("<"):
                                    msgs.append({"role": "user", "content": c["text"]})
                                    break
                    elif d.get("type") == "assistant":
                        content = d.get("message", {}).get("content", [])
                        if isinstance(content, str) and content.strip():
                            msgs.append({"role": "assistant", "content": content})
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text" and c["text"].strip():
                                    msgs.append({"role": "assistant", "content": c["text"]})
                                    break
                except:
                    pass
    print(json.dumps(msgs[-20:]))
