#!/usr/bin/env python3
"""List agent sessions as JSON for DMS Agent history.

A session belongs to a provider (claude by default). Claude Code and CheapVibeCode
are the same CLI on different gateways and share one transcript store, so both are
found by scanning it; Qoder and Kimi keep transcripts none of the plugin's filters
understand, so those are listed from the Jarvis session registry (see
sessions_registry.py).
"""
import json, os, glob, re, shlex, shutil, subprocess, sys, uuid

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
# Transcripts of the stock claude CLI (also run against the CVC gateway).
TRANSCRIPT_PROVIDERS = ("claude", "cvc")
# Providers registered in providers.json (acp/codex/claude-cli/openai). Their
# transcripts are in formats/scans the plugin does not own, so like qoder/kimi
# the Jarvis session registry is the only history — but the set is dynamic.
import registry as _prov_registry  # noqa: E402

# A corrupt providers.json must not take the built-in providers' history down
# with it; the registry providers are simply unknown then (the settings UI
# shows the corrupt file's error — here it stays a rejection, not a fallback).
try:
    REGISTRY_ENTRIES = _prov_registry.load().get("providers", {})
    REGISTRY_PROVIDERS = frozenset(REGISTRY_ENTRIES)
except _prov_registry.RegistryError:
    REGISTRY_ENTRIES = {}
    REGISTRY_PROVIDERS = frozenset()
if provider not in KNOWN_PROVIDERS and provider not in REGISTRY_PROVIDERS:
    print("history.py: unknown provider %r (known: %s)"
          % (provider, ", ".join(sorted(set(KNOWN_PROVIDERS) | REGISTRY_PROVIDERS))),
          file=sys.stderr)
    sys.exit(2)
REGISTRY_BACKED = provider not in TRANSCRIPT_PROVIDERS
OPENAI_BACKED = REGISTRY_ENTRIES.get(provider, {}).get("adapter") == "openai"
# "list --all-dirs": every directory with a registered Jarvis session, not
# just the current one. Each row carries its workDir (compound identity —
# the same id under two providers or two directories is two sessions).
ALL_DIRS = "list" in argv and "--all-dirs" in argv
if "--all-dirs" in argv:
    argv.remove("--all-dirs")
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


def openai_session(sid):
    try:
        parsed = uuid.UUID(sid)
        if parsed.version != 4 or str(parsed) != sid:
            return "", None
        state = os.path.expanduser(os.environ.get("XDG_STATE_HOME") or "~/.local/state")
        path = os.path.join(state, "dms-agent", "openai-sessions", sid + ".json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if (not isinstance(data, dict) or data.get("version") != 1 or data.get("id") != sid
                or data.get("provider") != provider or not isinstance(data.get("workDir"), str)
                or not isinstance(data.get("messages"), list)):
            return "", None
        return path, data
    except (ValueError, OSError, TypeError):
        return "", None


def is_agent_session(path):
    """Agent sessions come from `claude -p` (entrypoint "sdk-cli"); interactive
    Claude Code sessions started in the same directory are left out.

    The field decides, not the word: a session whose own text mentions
    "entrypoint" is still an agent session. The scan therefore goes on until it
    finds a record that has the field."""
    try:
        with open(path, encoding="utf-8") as fh:
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
    with open(path, encoding="utf-8") as fh:
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


def qoder_session_index(sid, work_dir=None):
    """The index qodercli --delete-session wants for this session id.

    The CLI lists its sessions as "  N. Title (age) [uuid]"; the index is the
    position in that list. It is matched on the uuid, never on the position
    the plugin remembers — the list grows and shrinks. The listing is scoped to
    the session's own working directory: `qodercli --list-sessions` only shows
    the current project, so measuring the index elsewhere either finds nothing
    or numbers a different session."""
    try:
        out = subprocess.run(["qodercli", "--list-sessions"], cwd=work_dir,
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
    index = qoder_session_index(sid, work_dir)
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
    if OPENAI_BACKED:
        root = os.path.expanduser(os.environ.get("XDG_STATE_HOME") or "~/.local/state")
        for path in glob.glob(os.path.join(root, "dms-agent", "openai-sessions", "*.json")):
            sid = os.path.basename(path)[:-5]
            _, data = openai_session(sid)
            if not data or (not ALL_DIRS and data["workDir"] != os.getcwd()):
                continue
            text = next((m.get("content", "") for m in data["messages"]
                         if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)), "")
            entry = registry_entry(provider, sid)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            title = entry["title"] if entry and entry["title"] else text[:60]
            results.append({"id": sid, "title": title, "name": title,
                            "date": int(mtime * 1000), "workDir": data["workDir"]})
        results.sort(key=lambda row: row["date"], reverse=True)
        print(json.dumps(results))
        sys.exit(0)
    if provider in TRANSCRIPT_PROVIDERS:
        # The files can vanish between the glob and the read (deleted from the
        # other panel); such a file is skipped, not fatal.
        dirs = {os.getcwd()}
        if ALL_DIRS:
            for shared_provider in TRANSCRIPT_PROVIDERS:
                dirs.update(e["workDir"] for e in sessions_registry.list(shared_provider))
        files = []
        for work_dir in dirs:
            for f in glob.glob(transcript_base(provider, work_dir) + "*.jsonl"):
                try:
                    files.append((os.path.getmtime(f), f, work_dir))
                except OSError:
                    continue
        files.sort(reverse=True)
        for _, f, work_dir in files:
            if not is_agent_session(f):
                continue
            sid = os.path.basename(f).replace(".jsonl", "")
            try:
                mtime = os.path.getmtime(f)
            except OSError:
                continue
            title = ""
            try:
                fh = open(f, encoding="utf-8")
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
                results.append({"id": sid, "title": name or title, "name": name,
                                "date": int(mtime * 1000), "workDir": work_dir})
                # Remember the session so other providers (and tools that cannot
                # scan Claude Code transcripts) can still see it in one place.
                # An "if absent" write: re-reading the history must not move a
                # session's place in the panel, and a rename must survive.
                if name or title:
                    # A read must not fail because the state dir is read-only
                    # or full: the list is the answer, the registry write is a
                    # side effect.
                    try:
                        sessions_registry.add_if_absent(provider, sid, name or title, work_dir)
                    except OSError:
                        pass
    else:
        # Qoder / Kimi / registry providers: transcripts are in formats the
        # plugin cannot scan; the registry is the only source of "sessions
        # this chat started". Without --all-dirs only this working directory
        # is listed: native `--resume` searches no further than the current
        # project, so anything else could not be reopened.
        here = os.getcwd()
        entries = sessions_registry.list(provider)
        if not ALL_DIRS:
            entries = [e for e in entries if e["workDir"] == here]
        for e in entries:
            results.append({"id": e["id"], "title": e["title"], "name": e["title"],
                            "date": int(e["ts"] * 1000), "workDir": e["workDir"]})
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
    entry_removed = False
    if sid and "/" not in sid and ".." not in sid:
        if provider in TRANSCRIPT_PROVIDERS:
            path = base + sid + ".jsonl"
            try:
                if os.path.isfile(path) and is_agent_session(path):
                    os.remove(path)
                    ok = True
                    forget_synced([sid])
            except OSError:
                # Unreadable/undeletable transcript: report a failure below,
                # never die with a traceback (the panel parses JSON only).
                ok = False
        elif OPENAI_BACKED:
            # The text transcript of a gateway session is this plugin's own
            # store, not an external CLI's: it can go from any directory (the
            # row shows its path for confirmation). Removing only the registry
            # entry would not hide it — the gateway listing scans the files.
            path, data = openai_session(sid)
            if data:
                try:
                    os.remove(path)
                    ok = True
                except OSError:
                    pass
        else:
            # Registry-backed providers: the transcript is only touched for a
            # session the registry knows — those are the ones this chat started.
            e = registry_entry(provider, sid)
            if e:
                ok = delete_via_cli(provider, sid, e["workDir"])
        # Registry policy. A transcript provider's foreign session is removed
        # from the list without touching its file (the plan's default for an
        # external session); a registry-backed session that could not be
        # deleted stays in the list, because the registry IS its only listing.
        if provider in TRANSCRIPT_PROVIDERS:
            e = registry_entry(provider, sid)
            foreign = e is not None and e["workDir"] != os.getcwd()
            stale = e is not None and not os.path.isfile(path)
            if ok or foreign or stale:
                sessions_registry.remove(provider, sid)
                entry_removed = True
                # Claude Code and CheapVibeCode share one transcript store,
                # so the session is gone for both of them.
                for other in TRANSCRIPT_PROVIDERS:
                    if other != provider:
                        sessions_registry.remove(other, sid)
        elif ok:
            sessions_registry.remove(provider, sid)
            entry_removed = True
    print(json.dumps({"deleted": 1 if ok else 0,
                      "removed": 1 if (ok or entry_removed) else 0}))

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
            try:
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
            except OSError:
                # A read-only transcript must not abort the rename: the
                # registry title still changes and the panel shows it.
                ok = False
        existed = registry_entry(provider, sid) is not None
        sessions_registry.rename(provider, sid, name)
        ok = ok or existed
    print(json.dumps({"renamed": 1 if ok else 0}))

elif action == "delete-all":
    removed = []
    if OPENAI_BACKED:
        root = os.path.expanduser(os.environ.get("XDG_STATE_HOME") or "~/.local/state")
        for path in glob.glob(os.path.join(root, "dms-agent", "openai-sessions", "*.json")):
            sid = os.path.basename(path)[:-5]
            checked, data = openai_session(sid)
            if data and data["workDir"] == os.getcwd():
                try:
                    os.remove(checked)
                    sessions_registry.remove(provider, sid)
                    removed.append(sid)
                except OSError:
                    pass
    elif provider in TRANSCRIPT_PROVIDERS:
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
        # with it. An entry whose file could not be removed stays in the list.
        here = os.getcwd()
        for e in sessions_registry.list(provider):
            if e["workDir"] != here:
                continue
            if e["id"] in removed or not os.path.isfile(base + e["id"] + ".jsonl"):
                sessions_registry.remove(provider, e["id"])
        # The other gateway's CLI shares the transcripts, so its entries go too.
        for other in TRANSCRIPT_PROVIDERS:
            if other != provider:
                for e in sessions_registry.list(other):
                    if e["workDir"] == here and (
                            e["id"] in removed or not os.path.isfile(base + e["id"] + ".jsonl")):
                        sessions_registry.remove(other, e["id"])
    else:
        # Only this working directory: the panel shows nothing else, and a
        # registry entry dropped for another one would take its transcript out
        # of that directory's history with it. The registry is the only
        # listing source for these providers, so a failed CLI delete must not
        # remove the entry — the user would lose a live session from history.
        here = os.getcwd()
        failed = 0
        for e in sessions_registry.list(provider):
            if e["workDir"] != here:
                continue
            if delete_via_cli(provider, e["id"], e["workDir"]):
                removed.append(e["id"])
                sessions_registry.remove(provider, e["id"])
            else:
                failed += 1
        print(json.dumps({"deleted": len(removed), "failed": failed}))
        sys.exit(0)
    print(json.dumps({"deleted": len(removed), "failed": 0}))

elif action == "restore":
    sid = argv[1] if len(argv) > 1 else ""
    if not sid or "/" in sid or ".." in sid:
        print(json.dumps({"messages": [], "model": "", "effort": "", "originDir": ""}))
        sys.exit(1)
    # Kimi's wire log is found by glob (see kimi_wire_file); everyone else is
    # the flat <id>.jsonl under the provider's transcript root. A registry
    # provider's session may live in another directory (the panel lists
    # --all-dirs): its workDir is the compound identity, so the transcript is
    # looked up there, not in the current one. Qoder keeps its old behavior:
    # the transcript next to the current directory, no registry lookup — its
    # sessions were never registry-scoped on restore.
    origin_dir = os.getcwd()
    requested_dir = argv[2] if len(argv) > 2 else ""
    shared = TRANSCRIPT_PROVIDERS if provider in TRANSCRIPT_PROVIDERS else (provider,)
    if requested_dir and requested_dir != origin_dir:
        _, openai_data = openai_session(sid) if OPENAI_BACKED else ("", None)
        known = openai_data and openai_data["workDir"] == requested_dir
        if not known and not any(e["workDir"] == requested_dir and e["id"] == sid
                                 for source in shared for e in sessions_registry.list(source)):
            print(json.dumps({"messages": [], "model": "", "effort": "", "originDir": requested_dir}))
            sys.exit(1)
        origin_dir = requested_dir
    if OPENAI_BACKED:
        _, data = openai_session(sid)
        if data and (not requested_dir or data["workDir"] == requested_dir):
            messages = [m for m in data["messages"] if isinstance(m, dict)
                        and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
            print(json.dumps({"messages": messages, "model": "", "effort": "", "originDir": data["workDir"]}))
        else:
            print(json.dumps({"messages": [], "model": "", "effort": "", "originDir": origin_dir}))
        sys.exit(0)
    if provider == "kimi":
        session_file = kimi_wire_file(sid)
        e = registry_entry(provider, sid)
        if e:
            origin_dir = e["workDir"]
    elif provider in TRANSCRIPT_PROVIDERS or provider == "qoder":
        # The transcript store is keyed by directory slug: this directory
        # first, then every directory the session registry remembers for the
        # provider (--all-dirs made those visible). A transcript found in
        # another directory is READ here, but its native --resume would not
        # find it back from the current one — the answer says so (originDir),
        # and the chat continues it as a context transfer, not a native one.
        session_file = transcript_base(provider, origin_dir) + sid + ".jsonl"
        if not requested_dir and not os.path.exists(session_file):
            search_providers = TRANSCRIPT_PROVIDERS if provider in TRANSCRIPT_PROVIDERS else (provider,)
            for source in search_providers:
                for e in sessions_registry.list(source):
                    if e["id"] != sid:
                        continue
                    candidate = transcript_base(provider, e["workDir"]) + sid + ".jsonl"
                    if os.path.exists(candidate):
                        session_file = candidate
                        origin_dir = e["workDir"]
                        break
                if origin_dir != os.getcwd():
                    break
    else:
        e = registry_entry(provider, sid)
        if e:
            origin_dir = e["workDir"]
        # ACP/Codex keep no transcript this plugin can read (transcript_base
        # is "" for them): an empty path, not "<sid>.jsonl" in the current
        # directory — that used to pick up a stray file of the same name.
        base_dir = transcript_base(provider, e["workDir"]) if e else ""
        session_file = (base_dir + sid + ".jsonl") if base_dir else ""
    msgs = []
    # The CLI stamps every reply with the model and effort it ran with; the last
    # reply tells what the session was using when it was left.
    model = effort = ""
    if os.path.exists(session_file):
        with open(session_file, encoding="utf-8") as f:
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
                                    text += c["text"]
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
                    elif d.get("type") == "assistant":
                        # Subagent replies and synthetic records say nothing about
                        # the chat's own model (the sidechain flag and a real id
                        # decide). The old "claude-" prefix filter also hid every
                        # gateway model: a CVC-style gateway runs "cvc/…", "kimi/…";
                        # "gpt-…", so per-session restore never worked there.
                        used = d.get("requestedModel") or d.get("message", {}).get("model") or ""
                        if not d.get("isSidechain") and used and not str(used).startswith("<"):
                            model = used
                            effort = d.get("effort") or effort
                        content = d.get("message", {}).get("content", [])
                        if isinstance(content, str) and content.strip():
                            msgs.append({"role": "assistant", "content": content})
                        elif isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text" and c["text"].strip():
                                    msgs.append({"role": "assistant", "content": c["text"]})
                except (ValueError, AttributeError, TypeError, KeyError):
                    pass
    print(json.dumps({"messages": msgs, "model": model, "effort": effort,
                      "originDir": origin_dir}))
