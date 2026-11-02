#!/usr/bin/env python3
"""List agent sessions as JSON for DMS Agent history.

A session belongs to a provider (claude by default). Claude Code and CheapVibeCode
are the same CLI on different gateways and share one transcript store, so both are
found by scanning it; Qoder and Kimi keep transcripts none of the plugin's filters
understand, so those are listed from the Jarvis session registry (see
sessions_registry.py).
"""
import json, os, glob, re, shlex, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sessions_registry  # noqa: E402

argv = sys.argv[1:]
provider = "claude"
if argv and argv[0].startswith("--provider="):
    provider = argv[0].split("=", 1)[1]
    argv = argv[1:]
elif "--provider" in argv:
    i = argv.index("--provider")
    provider = argv[i + 1] if i + 1 < len(argv) else "claude"
    del argv[i:i + 2]
action = argv[0] if argv else "list"
# The known providers. An unknown one is rejected: silently answering with the
# claude catalog (models.py) or with an empty history (here) would make the
# same wrong input give two different answers.
KNOWN_PROVIDERS = ("claude", "cvc", "qoder", "kimi")
if provider not in KNOWN_PROVIDERS:
    print("history.py: unknown provider %r (known: %s)"
          % (provider, ", ".join(KNOWN_PROVIDERS)), file=sys.stderr)
    sys.exit(2)
# Transcripts of the stock claude CLI (also run against the CVC gateway).
TRANSCRIPT_PROVIDERS = ("claude", "cvc")
# Every CLI stores sessions under a slug of the working directory
# (non-alphanumerics -> "-"); the agent and this script run from the same one.
TRANSCRIPT_ROOTS = {
    "claude": "~/.claude/projects",
    "cvc": "~/.claude/projects",
    "qoder": "~/.qoder/projects",
}


def transcript_base(provider, work_dir=None):
    root = TRANSCRIPT_ROOTS.get(provider)
    if root is None:
        return ""
    slug = re.sub(r"[^A-Za-z0-9]", "-", work_dir or os.getcwd())
    return os.path.join(os.path.expanduser(root), slug) + "/"


base = transcript_base(provider)


def kimi_wire_file(sid):
    """Kimi sessions live in ~/.kimi-code/sessions/wd_<slug>_<hash>/session_<id>/
    agents/main/wire.jsonl — the hash cannot be recomputed from the working
    directory, so the session is found by glob."""
    if not sid or "/" in sid or ".." in sid:
        return ""
    hits = glob.glob(os.path.expanduser("~/.kimi-code/sessions/*/")
                     + glob.escape(sid) + "/agents/main/wire.jsonl")
    return hits[0] if hits else ""


def registry_entry(provider, sid):
    for e in sessions_registry.list(provider):
        if e["id"] == sid:
            return e
    return None


def is_agent_session(path):
    """Agent sessions come from `claude -p` (entrypoint "sdk-cli"); interactive
    Claude Code sessions started in the same directory are left out.

    The field decides, not the word: a session whose own text mentions
    "entrypoint" is still an agent session. The scan therefore goes on until it
    finds a record that has the field."""
    try:
        with open(path) as fh:
            for i, line in enumerate(fh):
                if i > 50:
                    break
                if '"entrypoint"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and "entrypoint" in d:
                    return d.get("entrypoint") == "sdk-cli"
    except OSError:
        # The file can be deleted from the other panel between the glob and
        # this read; it is simply not a session then.
        return False
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


def qoder_session_index(sid):
    """The index qodercli --delete-session wants for this session id.

    The CLI lists its sessions as "  N. Title (age) [uuid]"; the index is the
    position in that list. It is matched on the uuid, never on the position
    the plugin remembers — the list grows and shrinks."""
    try:
        out = subprocess.run(["qodercli", "--list-sessions"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.stdout.splitlines():
        m = re.search(r"^\s*(\d+)\..*\[([0-9a-fA-F-]+)\]\s*$", line)
        if m and m.group(2) == sid:
            return int(m.group(1))
    return None


def delete_via_cli(provider, sid, work_dir):
    """Remove a session the way its own CLI does.

    Qoder and Kimi keep a transcript and a sidecar directory per session, and
    their CLIs know how to remove both. Deleting the files by hand leaves the
    CLI's own index pointing at a session that is gone.
    """
    if provider != "qoder":
        # Kimi has no session-deleting command; the files are what it has.
        b = transcript_base(provider, work_dir)
        if b:
            try:
                os.remove(b + sid + ".jsonl")
            except OSError:
                pass
            shutil.rmtree(b + sid, ignore_errors=True)  # the sidecar dir
        return True
    index = qoder_session_index(sid)
    if index is None:
        return False
    try:
        out = subprocess.run(["qodercli", "--delete-session", str(index)],
                             cwd=work_dir, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


if action == "list":
    results = []
    if provider in TRANSCRIPT_PROVIDERS:
        # The files can vanish between the glob and the read (deleted from the
        # other panel); such a file is skipped, not fatal.
        files = []
        for f in glob.glob(base + "*.jsonl"):
            try:
                os.path.getmtime(f)
            except OSError:
                continue
            files.append(f)
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        for f in [f for f in files if is_agent_session(f)][:20]:
            sid = os.path.basename(f).replace(".jsonl", "")
            try:
                mtime = os.path.getmtime(f)
            except OSError:
                continue
            title = ""
            try:
                fh = open(f)
            except OSError:
                continue
            with fh:
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
                    except (ValueError, AttributeError, TypeError):
                        pass
            if title:
                name = ""
                try:
                    name = custom_title(f)
                except OSError:
                    pass
                results.append({"id": sid, "title": name or title, "name": name, "date": int(mtime * 1000)})
                # Remember the session so other providers (and tools that cannot
                # scan Claude Code transcripts) can still see it in one place.
                # An "if absent" write: re-reading the history must not move a
                # session's place in the panel, and a rename must survive.
                if name or title:
                    sessions_registry.add_if_absent(provider, sid, name or title, os.getcwd())
    else:
        # Qoder / Kimi transcripts are in formats the plugin cannot scan; the
        # registry is the only source of "sessions this chat started". Only
        # this working directory is listed: `--resume` searches no further than
        # the current project, so anything else could not be reopened.
        here = os.getcwd()
        for e in [e for e in sessions_registry.list(provider) if e["workDir"] == here][:20]:
            results.append({"id": e["id"], "title": e["title"], "name": e["title"],
                            "date": int(e["ts"] * 1000)})
    print(json.dumps(results))

elif action == "register":
    # Qoder / Kimi transcripts cannot be told apart from the user's own TUI
    # sessions, so the id is remembered the moment the agent reports it. An
    # "if absent" write: a rename made between two turns must survive the next.
    sid = argv[1] if len(argv) > 1 else ""
    name = " ".join(" ".join(argv[2:]).split()) if len(argv) > 2 else ""
    ok = False
    if sid and "/" not in sid and ".." not in sid:
        ok = sessions_registry.add_if_absent(provider, sid, name, os.getcwd())
    print(json.dumps({"registered": 1 if ok else 0}))

elif action == "delete":
    # Only ever removes agent sessions: an interactive Claude Code session
    # started in the same directory must survive, and the id arrives from the
    # outside, so it is checked rather than trusted.
    sid = argv[1] if len(argv) > 1 else ""
    ok = False
    if sid and "/" not in sid and ".." not in sid:
        if provider in TRANSCRIPT_PROVIDERS:
            path = base + sid + ".jsonl"
            if os.path.isfile(path) and is_agent_session(path):
                os.remove(path)
                ok = True
                forget_synced([sid])
        else:
            # Registry-backed providers: the transcript is only touched for a
            # session the registry knows — those are the ones this chat started.
            e = registry_entry(provider, sid)
            if e:
                ok = delete_via_cli(provider, sid, e["workDir"])
        # The registry entry goes in every case: the panel must not offer a
        # session that is gone. But a session that could not be removed is
        # still a failed delete — "deleted: 0" says so.
        sessions_registry.remove(provider, sid)
        # Claude Code and CheapVibeCode are the same CLI on two gateways and
        # share one transcript store. The session is therefore gone for both,
        # and the other one's registry entry would keep a session that no
        # longer exists in the panel.
        for other in TRANSCRIPT_PROVIDERS:
            if other != provider:
                sessions_registry.remove(other, sid)
    print(json.dumps({"deleted": 1 if ok else 0}))

elif action == "rename":
    # Same records /rename writes, so the new name also shows up in the CLI's
    # /resume. An empty name drops back to the automatic title. Checked like
    # delete: the id and the name arrive from the outside.
    sid = argv[1] if len(argv) > 1 else ""
    name = " ".join((argv[2] if len(argv) > 2 else "").split())[:100]
    ok = False
    if sid and "/" not in sid and ".." not in sid:
        if provider in TRANSCRIPT_PROVIDERS:
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
        existed = registry_entry(provider, sid) is not None
        sessions_registry.rename(provider, sid, name)
        ok = ok or existed
    print(json.dumps({"renamed": 1 if ok else 0}))

elif action == "delete-all":
    removed = []
    if provider in TRANSCRIPT_PROVIDERS:
        for f in glob.glob(base + "*.jsonl"):
            if is_agent_session(f):
                try:
                    os.remove(f)
                    removed.append(os.path.basename(f)[:-len(".jsonl")])
                except OSError:
                    pass
        forget_synced(removed)
        # Only this working directory, like the registry-backed providers: the
        # panel shows nothing else, and a registry entry dropped for another
        # directory would take its transcript out of that directory's history
        # with it.
        here = os.getcwd()
        for e in sessions_registry.list(provider):
            if e["workDir"] != here:
                continue
            sessions_registry.remove(provider, e["id"])
            if e["id"] not in removed:
                removed.append(e["id"])
        # The other gateway's CLI shares the transcripts, so its entries go too.
        for other in TRANSCRIPT_PROVIDERS:
            if other != provider:
                for e in sessions_registry.list(other):
                    if e["workDir"] == here:
                        sessions_registry.remove(other, e["id"])
    else:
        # Only this working directory: the panel shows nothing else, and a
        # registry entry dropped for another one would take its transcript out
        # of that directory's history with it.
        here = os.getcwd()
        for e in sessions_registry.list(provider):
            if e["workDir"] != here:
                continue
            if delete_via_cli(provider, e["id"], e["workDir"]):
                removed.append(e["id"])
            sessions_registry.remove(provider, e["id"])
    print(json.dumps({"deleted": len(removed)}))

elif action == "restore":
    sid = argv[1] if len(argv) > 1 else ""
    # Kimi's wire log is found by glob (see kimi_wire_file); everyone else is
    # the flat <id>.jsonl under the provider's transcript root.
    session_file = kimi_wire_file(sid) if provider == "kimi" else base + sid + ".jsonl"
    msgs = []
    # The CLI stamps every reply with the model and effort it ran with; the last
    # reply tells what the session was using when it was left.
    model = effort = ""
    if os.path.exists(session_file):
        with open(session_file) as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get("type") == "runtime-config":
                        # Qoder stamps the session's model and effort here; a
                        # null effort means the CLI's default. Claude Code
                        # writes no such records — it stamps every reply.
                        model = d.get("model") or model
                        effort = d.get("reasoningEffort") or effort
                    elif d.get("type") == "profile.bind":
                        # Kimi wires the run's model and effort into the first
                        # record of the wire log (state.json has none).
                        model = d.get("modelAlias") or model
                        effort = d.get("thinkingEffort") or effort
                    elif d.get("type") == "agent.message.appended":
                        # Kimi chat messages; "think" blocks and tool results
                        # are not chat content.
                        inner = d.get("message", {}).get("message", {})
                        role = inner.get("role")
                        if role not in ("user", "assistant"):
                            continue
                        content = inner.get("content", "")
                        text = content if isinstance(content, str) else ""
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip():
                                    text = c["text"]
                                    break
                        if text and not text.startswith("<"):
                            msgs.append({"role": role, "content": text})
                    elif d.get("type") == "user" and not d.get("isMeta"):
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
                except (ValueError, AttributeError, TypeError, KeyError):
                    pass
    print(json.dumps({"messages": msgs[-20:], "model": model, "effort": effort}))
