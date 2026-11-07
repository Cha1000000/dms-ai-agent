#!/usr/bin/env python3
"""ACP bridge: an ACP agent (JSON-RPC 2.0 over stdio) -> canonical claude
stream-json for DMS Agent.

Usage: acp_bridge.py <agent-command...>   (argv directly, no shell)

stdin  (from AgentService.qml), one JSON per line:
  {"type":"user","message":{"role":"user","content":[{...canon content...}]}}
  {"type":"config","model":"...","effort":"...","resumeId":"..."}   (optional)
  {"type":"control_response","response":{"subtype":"success","request_id":X,
      "response":{"behavior":"allow"|"deny",...}}}
  {"type":"cancel"}

stdout (to AgentService.qml), one JSON per line — the canonical claude
stream-json events the service already parses:
  {"type":"assistant","message":{"content":[...]}}
  {"type":"user","message":{"content":[{tool_result...}]}}   (tool updates)
  {"type":"result","session_id":S,"is_error":bool,"result":str,
   "errors":[...],"total_cost_usd":null,"usage":null}

Exactly one result per finished turn. The bridge owns one agent process; the
ACP session is created on the first turn and reused, so a resumeId in a
config line maps to session/load.

Protocol details that matter (checked against the spec and live agents):
  - session/request_permission is answered with the optionId of the option
    whose kind matches the user's choice; a behavior without a matching
    option is answered outcome=cancelled and ends the turn with an error —
    no invented ids, no one-time turned into always.
  - session/cancel is a notification. Every pending permission request gets
    outcome=cancelled; the pending prompt returns (end_turn or an error),
    and the bridge ends the turn with a cancelled result.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import queue
import time

JSONRPC = "2.0"

_pending_permissions = {}          # rpc id -> our interface request id (string)
_permission_queue = queue.Queue()  # rpc id -> user control_response
_state_lock = threading.Lock()
_state = {
    "rpc_id": 0,
    "session": "",
    # No turn is in flight at startup, so an initialize/session failure can
    # emit its own error result instead of being swallowed by the guard.
    "turn_done": True,
    "cancelled": False,
    "waiting": False,              # a session/prompt is in flight
    "replaying": False,            # session/load streams the old history
    "turn_text": [],
}

_pending_rpc = {}                  # rpc id -> queue to receive the response
_pending_permission_options = {}   # rpc id -> options offered to the UI
_ui_permission_ids = {}            # our interface id -> rpc id


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


_agent_proc = [None]


def agent_send(obj):
    """A message to the AGENT's stdin — not the bridge's stdout."""
    proc = _agent_proc[0]
    if proc is None or proc.stdin is None:
        raise RuntimeError("agent is not running")
    proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def next_id():
    with _state_lock:
        _state["rpc_id"] += 1
        return _state["rpc_id"]


def rpc(method, params, timeout=None):
    """Send a request, return the response (or raise on error response).

    Every call is bounded: an agent that never answers initialize/session/new
    used to block the bridge (and the chat on "processing") forever. A timeout
    is an RpcError, which the callers already turn into an error result."""
    rid = next_id()
    q = queue.Queue(maxsize=1)
    with _state_lock:
        _pending_rpc[rid] = q
    agent_send({"jsonrpc": JSONRPC, "id": rid, "method": method, "params": params})
    try:
        item = q.get(timeout=timeout or float(os.environ.get("ACP_RPC_TIMEOUT", "120")))
    except queue.Empty:
        raise RpcError({"code": -32000, "message": "timeout waiting for %s" % method})
    finally:
        with _state_lock:
            _pending_rpc.pop(rid, None)
    if isinstance(item, dict) and "error" in item:
        raise RpcError(item["error"])
    return item.get("result", {}) if isinstance(item, dict) else {}


class RpcError(Exception):
    pass


# --- canonisation ------------------------------------------------------------

def acp_content_to_canon(content):
    """ACP ContentBlock -> claude stream-json content block."""
    if not isinstance(content, dict):
        return None
    t = content.get("type")
    if t == "text":
        return {"type": "text", "text": content.get("text", "")}
    if t == "thinking":
        return {"type": "thinking", "thinking": content.get("thinking", "")}
    if t == "tool_call":
        return {"type": "tool_use", "id": content.get("toolCallId", ""),
                "name": content.get("kind", "tool"), "input": {}}
    if t == "tool_call_update":
        # A finished tool call: a tool_result-shaped user event so the chat
        # shows what ran. Output lives in content[0].text.
        raw = content.get("content") or []
        text = ""
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            text = raw[0].get("text", "")
        return {"type": "tool_result", "tool_use_id": content.get("toolCallId", ""),
                "content": text}
    if t == "image":
        return {"type": "text", "text": "[image]"}
    return None


def load_context_blocks():
    """One-shot context transfer: [{"role","content"}] JSONL -> ACP text
    blocks prepended to the first turn. A missing/unreadable file is a turn
    error, never silently ignored."""
    path = ""
    with _state_lock:
        path = _state.get("config", {}).get("contextFile", "")
    if not path:
        return []
    blocks = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if isinstance(d, dict) and d.get("role") in ("user", "assistant") \
                    and isinstance(d.get("content"), str):
                blocks.append({"type": "text",
                               "text": "%s: %s" % ("User" if d["role"] == "user" else "Assistant",
                                                   d["content"])})
    return blocks


def canon_to_acp_content(content):
    """Canonical user content -> ACP ContentBlock list (text only)."""
    blocks = []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    for c in content or []:
        if isinstance(c, dict) and c.get("type") == "text":
            blocks.append({"type": "text", "text": c.get("text", "")})
        elif isinstance(c, str):
            blocks.append({"type": "text", "text": c})
    return blocks


def emit_assistant(blocks):
    if blocks:
        out({"type": "assistant", "message": {"role": "assistant", "content": blocks}})


def emit_result(session_id, is_error, text, errors=None):
    with _state_lock:
        if _state["turn_done"]:
            return
        _state["turn_done"] = True
    out({"type": "result", "session_id": session_id or "", "is_error": is_error,
         "result": text, "errors": errors or [], "total_cost_usd": None,
         "usage": None})


# --- agent stdout reader ------------------------------------------------------

def handle_update(update):
    if not isinstance(update, dict):
        return
    # session/load streams the WHOLE previous conversation back as
    # notifications. They arrive before the new prompt and are not the answer:
    # showing them as fresh messages (and joining them into the result) made
    # every resumed ACP turn repeat its own history.
    with _state_lock:
        replaying = _state.get("replaying", False)
    if replaying:
        return
    kind = update.get("sessionUpdate")
    if kind == "agent_message_chunk":
        block = acp_content_to_canon(update.get("content"))
        if block and block.get("type") == "text":
            with _state_lock:
                if _state["waiting"] and not _state["turn_done"]:
                    _state["turn_text"].append(block.get("text", ""))
            emit_assistant([block])
    elif kind == "agent_thought_chunk":
        block = acp_content_to_canon(update.get("content"))
        if block:
            emit_assistant([{"type": "thinking", "thinking": block.get("text", block.get("thinking", ""))}])
    elif kind in ("tool_call", "tool_call_update"):
        block = acp_content_to_canon(update)
        if block:
            if block.get("type") == "tool_use":
                emit_assistant([{"type": "tool_use", "id": block["id"],
                                 "name": update.get("title") or block.get("name", "tool"),
                                 "input": block.get("input", {})}])
            else:
                out({"type": "user", "message": {"role": "user", "content": [block]}})
    elif kind == "config_option_update":
        with _state_lock:
            _state["config_options"] = config_options_from(update)
    elif kind == "plan":
        pass  # not shown in the chat
    elif kind == "available_commands_update":
        pass
    elif kind == "current_mode_update":
        pass


def handle_agent_request(req):
    """A request FROM the agent (e.g. session/request_permission)."""
    method = req.get("method", "")
    rid = req.get("id")
    params = req.get("params", {}) or {}
    if not isinstance(params, dict):
        params = {}
    if method == "session/request_permission":
        options = params.get("options", []) or []
        tool_call = params.get("toolCall") or {}
        if not isinstance(tool_call, dict):
            tool_call = {}
        title = tool_call.get("title") or tool_call.get("kind") or "tool"
        raw_input = tool_call.get("rawInput")
        # The chat reads the canonical claude fields (tool_name/input); the
        # ACP-specific fields stay for anything that wants them.
        ui_id = "perm-%d" % next_id()
        with _state_lock:
            _pending_permissions[rid] = ui_id
            _ui_permission_ids[ui_id] = rid
        _pending_permission_options[rid] = options
        out({"type": "control_request", "request_id": ui_id,
             "request": {"subtype": "can_use_tool",
                         "tool_name": title,
                         "input": raw_input if isinstance(raw_input, dict) else {},
                         "tool_call": title,
                         "options": options}})
        return
    # Unknown agent request: a protocol error so it never blocks the loop.
    agent_send({"jsonrpc": JSONRPC, "id": rid,
                "error": {"code": -32601, "message": "unsupported request: %s" % method}})


def cancel_permission(rpc_id):
    with _state_lock:
        ui_id = _pending_permissions.pop(rpc_id, None)
        if ui_id is not None:
            _ui_permission_ids.pop(ui_id, None)
        _pending_permission_options.pop(rpc_id, None)
    agent_send({"jsonrpc": JSONRPC, "id": rpc_id,
                "result": {"outcome": {"outcome": "cancelled"}}})


def reader(proc):
    """Read the agent's stdout: responses, notifications, requests."""
    try:
        _reader_inner(proc)
    except Exception:
        import traceback
        traceback.print_exc()
        raise


def _reader_inner(proc):
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if os.environ.get("ACP_BRIDGE_DEBUG"):
            sys.stderr.write("BRIDGE<- %s\n" % line[:200]); sys.stderr.flush()
        if "id" in msg and ("method" not in msg):
            rid = msg["id"]
            with _state_lock:
                pending_perm = rid in _pending_permissions
            # A response to a permission request is handled by the turn loop,
            # not routed as an RPC answer; a stale one is dropped there.
            if pending_perm:
                continue
            q = _pending_rpc.get(rid)
            if q is not None:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass
                continue
        if "method" in msg and "id" in msg:
            handle_agent_request(msg)
            continue
        if msg.get("method") == "session/update":
            params = msg.get("params")
            # A malformed notification from a newer agent must not kill the
            # reader thread and leave a bridge that can never finish a turn.
            if isinstance(params, dict):
                handle_update(params.get("update", {}))
            continue
    # EOF: the agent died; end the turn if one is running.
    out({"type": "bridge_event", "event": "eof"})
    with _state_lock:
        waiting = _state["waiting"]
    if waiting:
        with _state_lock:
            sid = _state["session"]
        emit_result(sid, True, "", ["agent exited before finishing the turn"])


# --- permission resolution ----------------------------------------------------

def resolve_permission(resp, options):
    """Map the user's allow/deny to a REAL optionId from the offered options."""
    behavior = (resp.get("response") or {}).get("behavior")
    wanted_kind = "allow_once" if behavior == "allow" else "reject_once"
    for opt in options:
        if opt.get("kind") == wanted_kind:
            return opt.get("optionId")
    return None


def cancel_all_permissions():
    with _state_lock:
        ids = list(_pending_permissions)
    for rid in ids:
        cancel_permission(rid)


def take_permission_answer(resp):
    """Our interface request id -> the still-open JSON-RPC request.

    The id shown to the chat is bridge-minted ("perm-3"), so a string or an
    integer JSON-RPC id from the agent is irrelevant here; an answer for a
    request that was already answered or cancelled is dropped instead of being
    sent to the agent a second time (two results for one id) or applied to the
    next turn.
    """
    ui_id = str((resp or {}).get("request_id", ""))
    with _state_lock:
        rid = _ui_permission_ids.pop(ui_id, None)
        if rid is None:
            return None
        _pending_permissions.pop(rid, None)
        options = _pending_permission_options.pop(rid, [])
    return rid, resp, options


# --- stdin (service) reader ----------------------------------------------------

def config_options_from(result):
    return result.get("configOptions", []) or []


def models_from(result):
    """The second ACP config shape: models.availableModels (gemini-cli 0.66).

    The first shape is configOptions + session/set_config_option; this one is
    models.availableModels + session/set_model. Both are in the spec, agents
    pick one."""
    models = result.get("models")
    if not isinstance(models, dict):
        return []
    rows = models.get("availableModels")
    return rows if isinstance(rows, list) else []


def current_model_from(result):
    models = result.get("models")
    if isinstance(models, dict):
        return models.get("currentModelId", "") or ""
    return ""


def apply_model_via_models(sid, want):
    """Select the model in the models/set_model shape. Returns an error list."""
    with _state_lock:
        rows = _state.get("models", [])
        current = _state.get("current_model", "")
    ids = [r.get("modelId") for r in rows if isinstance(r, dict) and r.get("modelId")]
    if not ids:
        return ["config model: option unavailable or ambiguous"]
    if want not in ids:
        # The agent may accept an unknown id without a word (gemini does), so
        # the check is ours: the model must be in the list it offered.
        return ["config model: %s not offered" % want]
    if current == want:
        return []
    try:
        rpc("session/set_model", {"sessionId": sid, "modelId": want})
    except RpcError as e:
        return ["config model rejected: %s" % e]
    with _state_lock:
        _state["current_model"] = want
    return []


def apply_config(sid, cfg, allow_missing_model=False):
    """Apply and verify requested settings against the agent's config options.

    allow_missing_model: a resumed session whose LoadSessionResponse carries no
    configOptions (optional in ACP v1). The agent then keeps the model the
    session was created with; there is nothing to set and nothing to fail."""
    for field in ("model", "effort"):
        want = cfg.get(field)
        if not want:
            continue
        with _state_lock:
            options = _state.get("config_options", [])
        categories = ("effort", "thought_level") if field == "effort" else (field,)
        matches = [o for o in options if isinstance(o, dict) and o.get("category") in categories]
        if len(matches) != 1 or not matches[0].get("id") or matches[0].get("type") != "select":
            if field == "model":
                # The second config shape (models.availableModels +
                # session/set_model).
                errors = apply_model_via_models(sid, want)
                with _state_lock:
                    have_catalog = bool(_state.get("models"))
                if errors and have_catalog:
                    return errors
                if errors and not allow_missing_model:
                    return errors
                continue
            if len(matches) == 0:
                return ["config %s: option unavailable" % field]
            return ["config %s: option unavailable or ambiguous" % field]
        option = matches[0]
        values = []
        for entry in option.get("options", []) or []:
            if isinstance(entry, dict):
                if "value" in entry:
                    values.append(entry["value"])
                for nested in entry.get("options", []) or []:
                    if isinstance(nested, dict) and "value" in nested:
                        values.append(nested["value"])
        if want not in values:
            return ["config %s: %s not offered" % (field, want)]
        if option.get("currentValue") == want:
            continue
        try:
            # The option id is sent under both names: the spec says
            # "configOptionId", opencode reads "configId". Extra fields are
            # ignored by the agents that use the other one.
            resp = rpc("session/set_config_option",
                       {"sessionId": sid, "configOptionId": option["id"],
                        "configId": option["id"], "value": want})
        except RpcError as e:
            return ["config %s rejected: %s" % (field, e)]
        updated = config_options_from(resp)
        with _state_lock:
            _state["config_options"] = updated
        confirmed = [o for o in updated if isinstance(o, dict) and o.get("id") == option["id"]]
        if len(confirmed) != 1 or confirmed[0].get("currentValue") != want:
            return ["config %s: selection not confirmed" % field]
    return []


_service_queue = queue.Queue()  # user/config/cancel lines from the service


def stdin_reader():
    """stdin lives in its own thread: run_turn blocks the main loop while it
    waits for the prompt, and the permission answers it waits for arrive on
    that same stdin — a single-threaded reader deadlocks."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        # Permission answers and cancel are consumed immediately: a running
        # turn blocks the main dispatcher while it waits for exactly these.
        mtype = msg.get("type")
        if mtype == "control_response":
            resolved = take_permission_answer(msg.get("response") or {})
            if resolved is not None:
                _permission_queue.put(resolved)
            continue
        if mtype == "cancel":
            do_cancel()
            continue
        _service_queue.put(msg)
    _service_queue.put(None)  # EOF


def do_cancel():
    """session/cancel to the agent, cancelled outcomes to the pending
    permission requests, an error result to close the turn."""
    with _state_lock:
        _state["cancelled"] = True
        session = _state["session"]
        waiting = _state["waiting"]
    if session:
        agent_send({"jsonrpc": JSONRPC, "method": "session/cancel",
                    "params": {"sessionId": session}})
    cancel_all_permissions()
    if waiting:
        emit_result(session, True, "cancelled by user", ["cancelled"])


def service_loop(proc):
    while True:
        msg = _service_queue.get()
        if msg is None:
            return
        mtype = msg.get("type")
        if mtype == "config":
            with _state_lock:
                _state["config"] = {k: msg.get(k) for k in ("model", "effort", "resumeId", "contextFile")}
            continue
        if mtype == "control_response":
            resolved = take_permission_answer(msg.get("response") or {})
            if resolved is not None:
                _permission_queue.put(resolved)
            continue
        if mtype == "cancel":
            do_cancel()
            continue
        if mtype == "user":
            run_turn(msg)


def run_turn(msg):
    cfg = {}
    with _state_lock:
        cfg = _state.get("config", {})
        resume_id = cfg.get("resumeId", "")
        # A new turn resets the flag only after the previous result went out —
        # enforced by turn_done guard in emit_result.
        _state["turn_done"] = False
        _state["cancelled"] = False
        _state["waiting"] = True
        _state["turn_text"] = []
        # session/load and session/new may stream updates that belong to the
        # session's history, not to this turn: drop them until the prompt is
        # actually sent.
        _state["replaying"] = True

    try:
        sid = ensure_session(resume_id)
        if sid is None:
            return
        with _state_lock:
            _state["session"] = sid

        errors = apply_config(sid, cfg, allow_missing_model=bool(resume_id))
        if errors:
            emit_result(sid, True, "", errors)
            return
        if _state["cancelled"]:
            emit_result(sid, True, "cancelled by user", errors or ["cancelled"])
            return

        content = canon_to_acp_content(msg.get("message", {}).get("content"))
        try:
            ctx = load_context_blocks()
        except Exception as e:
            emit_result(sid, True, "", ["cannot read context file: %s" % e])
            return
        if ctx:
            content = ctx + content
        prompt_id = next_id()
        prompt_q = queue.Queue(maxsize=1)
        with _state_lock:
            _pending_rpc[prompt_id] = prompt_q
            # History replay (session/load) stops counting as replay only when
            # the real prompt goes out; config updates in between are not part
            # of the turn's answer either.
            _state["replaying"] = False
        agent_send({"jsonrpc": JSONRPC, "id": prompt_id, "method": "session/prompt",
                    "params": {"sessionId": sid, "prompt": content}})

        # Drive the turn: wait for the prompt response; while it runs, answer
        # permission requests as the user replies.
        turn_errors = list(errors)
        prompt_answer = None
        turn_deadline = time.monotonic() + float(os.environ.get("ACP_TURN_TIMEOUT", "300"))
        while True:
            # Cancel, EOF and the timeout emit the turn's result from another
            # thread. Leave the loop for it instead of spinning until the
            # prompt reply arrives (up to five minutes) with the next message
            # stuck behind this one.
            with _state_lock:
                finished_elsewhere = _state["turn_done"]
            if finished_elsewhere:
                with _state_lock:
                    _pending_rpc.pop(prompt_id, None)
                break
            if time.monotonic() > turn_deadline:
                agent_send({"jsonrpc": JSONRPC, "method": "session/cancel",
                            "params": {"sessionId": sid}})
                cancel_all_permissions()
                emit_result(sid, True, "", turn_errors + ["turn timed out"])
                return
            # Any pending permission the user answered?
            try:
                rid, resp, opts = _permission_queue.get(timeout=0.1)
                option_id = resolve_permission(resp, opts)
                if option_id is None:
                    # No safe mapping: refuse rather than invent an id.
                    cancel_permission(rid)
                    turn_errors.append("permission %s: no matching option" % rid)
                    emit_result(sid, True, "", turn_errors)
                    return
                agent_send({"jsonrpc": JSONRPC, "id": rid,
                            "result": {"outcome": {"outcome": "selected",
                                                   "optionId": option_id}}})
                continue
            except queue.Empty:
                pass

            try:
                prompt_answer = prompt_q.get(timeout=0.1)
                with _state_lock:
                    _pending_rpc.pop(prompt_id, None)
                break
            except queue.Empty:
                pass

        with _state_lock:
            _state["waiting"] = False
        if prompt_answer is None:
            # The turn was ended elsewhere (cancel/EOF); its result is out.
            return
        if "error" in prompt_answer:
            emit_result(sid, True, "", [prompt_answer["error"].get("message", "prompt failed")])
            return
        stop = (prompt_answer.get("result") or {}).get("stopReason", "end_turn")
        if stop not in ("end_turn",):
            emit_result(sid, stop == "refusal", "", ["stopped: %s" % stop])
            return
        with _state_lock:
            text = "".join(_state["turn_text"])
        emit_result(sid, bool(turn_errors), text, turn_errors)
    except Exception as e:  # never leave the turn hanging
        with _state_lock:
            sid = _state.get("session", "")
        emit_result(sid, True, "", ["bridge error: %s" % e])
        raise
    finally:
        # A turn that ended on an early return (config error, cancel) must not
        # leave "waiting" set: the EOF handler would report a dead agent as a
        # second failure of a turn that is already over.
        with _state_lock:
            _state["waiting"] = False
            _state["replaying"] = False


def ensure_session(resume_id):
    with _state_lock:
        sid = _state.get("session", "")
    if sid:
        return sid
    try:
        if resume_id:
            result = rpc("session/load", {"sessionId": resume_id, "cwd": os.getcwd(),
                                          "mcpServers": []})
            sid = resume_id
        else:
            result = rpc("session/new", {"cwd": os.getcwd(), "mcpServers": []})
            sid = result.get("sessionId", "")
        with _state_lock:
            # session/load may legitimately carry neither configOptions nor a
            # models list (LoadSessionResponse.configOptions is optional): keep
            # what the process already knows instead of wiping the catalog and
            # failing every model selection.
            loaded_options = config_options_from(result)
            loaded_models = models_from(result)
            if loaded_options:
                _state["config_options"] = loaded_options
            if loaded_models:
                _state["models"] = loaded_models
            current = current_model_from(result)
            if current:
                _state["current_model"] = current
    except RpcError as e:
        emit_result("", True, "", ["cannot start session: %s" % e])
        return None
    if not sid:
        emit_result("", True, "", ["agent returned no session id"])
        return None
    return sid


def stop_agent(proc=None, force=False):
    """Terminate the agent AND its descendants.

    The agent is started in its own process group, so a tool process it
    spawned cannot outlive the bridge when Stop kills the bridge."""
    proc = proc or _agent_proc[0]
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        try:
            proc.kill() if force else proc.terminate()
        except OSError:
            pass


def _on_term(signum, frame):
    proc = _agent_proc[0]
    stop_agent(proc)
    try:
        if proc is not None:
            proc.wait(timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        stop_agent(proc, force=True)
    sys.exit(0)


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: acp_bridge.py <agent-command...>\n")
        sys.exit(2)
    proc = subprocess.Popen(sys.argv[1:], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=None, text=True,
                            bufsize=1, start_new_session=True)
    _agent_proc[0] = proc
    # Stop in the chat SIGTERMs the bridge; without this the agent (and any
    # tool process it started) would keep running with nobody reading it.
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    t = threading.Thread(target=reader, args=(proc,), daemon=True)
    t.start()
    st = threading.Thread(target=stdin_reader, daemon=True)
    st.start()
    # clientCapabilities.fs is an OBJECT in the ACP schema, not a boolean:
    # gemini --acp rejects `{"fs": false}` with "expected 'object', received
    # boolean". Only the capabilities the bridge really implements are listed.
    try:
        rpc("initialize", {"protocolVersion": 1, "clientCapabilities": {"fs": {}}})
    except Exception as e:
        emit_result("", True, "", ["initialize failed: %s" % e])
        stop_agent(proc, force=True)
        sys.exit(1)
    try:
        service_loop(proc)
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            stop_agent(proc, force=True)


if __name__ == "__main__":
    main()
