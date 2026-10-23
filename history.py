#!/usr/bin/env python3
"""List Claude Code sessions as JSON for DMS Agent history."""
import json, os, glob, re, shlex, shutil, subprocess, sys

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


def forget_synced(ids):
    """ccsync (github.com/Cha1000000/claude-code-sync) keeps a copy of every
    session and lays a deleted one back on its next pull. Where it is set up,
    deleting also forgets the session there: the copy leaves the vault and the
    other machines drop theirs. It does a git pull and push per session, so it
    runs on its own and the history does not wait for it."""
    engine = os.path.expanduser("~/claude-sync-vault/bin/ccsync.py")
    if not ids or not os.path.isfile(engine):
        return
    # One after another, as each run commits to the same git repo; one that
    # fails (no network) does not stop the rest.
    script = "; ".join("python3 %s forget --yes --session %s --reason 'deleted in DMS Agent'"
                       % (shlex.quote(engine), shlex.quote(sid)) for sid in ids)
    # Deleting rows one by one starts a run per row; flock queues them too.
    command = ["sh", "-c", script]
    if shutil.which("flock"):
        lock = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "dms-agent-forget.lock")
        command = ["flock", lock] + command
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass  # the session is gone here anyway; the vault keeps its copy as before


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
            name = custom_title(f)
            results.append({"id": sid, "title": name or title, "name": name, "date": int(mtime * 1000)})
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
            forget_synced([sid])
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
    removed = []
    for f in glob.glob(base + "*.jsonl"):
        if is_agent_session(f):
            try:
                os.remove(f)
                removed.append(os.path.basename(f)[:-len(".jsonl")])
            except OSError:
                pass
    forget_synced(removed)
    print(json.dumps({"deleted": len(removed)}))

elif action == "restore":
    sid = sys.argv[2] if len(sys.argv) > 2 else ""
    session_file = base + sid + ".jsonl"
    msgs = []
    # The CLI stamps every reply with the model and effort it ran with; the last
    # reply tells what the session was using when it was left.
    model = effort = ""
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
                        # Subagent replies and synthetic or gateway records say nothing about
                        # the chat's own model. Older CLIs have no requestedModel.
                        used = d.get("requestedModel") or d.get("message", {}).get("model") or ""
                        if not d.get("isSidechain") and used.startswith("claude-"):
                            model = used
                            effort = d.get("effort") or effort
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
    print(json.dumps({"messages": msgs[-20:], "model": model, "effort": effort}))
