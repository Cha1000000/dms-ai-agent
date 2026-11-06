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
import subprocess
import sys
import threading
import queue
import time

JSONRPC = "2.0"

_pending_permissions = {}          # rpc id -> None (open requests)
_permission_queue = queue.Queue()  # rpc id -> user control_response
_state_lock = threading.Lock()
_state = {
    "rpc_id": 0,
    "session": "",
    "turn_done": False,            # result emitted for the current turn
    "cancelled": False,
    "waiting": False,              # a session/prompt is in flight
}

_pending_rpc = {}                  # rpc id -> queue to receive the response
_pending_permission_options = {}   # rpc id -> options offered to the UI


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
    """Send a request, return the response (or raise on error response)."""
    rid = next_id()
    q = queue.Queue(maxsize=1)
    with _state_lock:
        _pending_rpc[rid] = q
    agent_send({"jsonrpc": JSONRPC, "id": rid, "method": method, "params": params})
    item = q.get(timeout=timeout) if timeout else q.get()
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
    if method == "session/request_permission":
        with _state_lock:
            _pending_permissions[rid] = None
        options = params.get("options", []) or []
        _pending_permission_options[rid] = options
        out({"type": "control_request", "request_id": str(rid),
             "request": {"subtype": "can_use_tool",
                         "tool_call": params.get("toolCall", {}).get("title", "tool"),
                         "options": options}})
        return
    # Unknown agent request: a protocol error so it never blocks the loop.
    agent_send({"jsonrpc": JSONRPC, "id": rid,
                "error": {"code": -32601, "message": "unsupported request: %s" % method}})


def cancel_permission(rpc_id):
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
            if pending_perm and _state["cancelled"]:
                # Response to a request we already cancelled.
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
            handle_update(msg.get("params", {}).get("update", {}))
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
        _pending_permissions.clear()
    for rid in ids:
        cancel_permission(rid)


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


def apply_config(sid, cfg):
    """Apply and verify requested settings against the agent's config options."""
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
                errors = apply_model_via_models(sid, want)
                if errors:
                    return errors
                continue
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
            resp = msg.get("response", {}) or {}
            try:
                rid = int(resp.get("request_id"))
            except (TypeError, ValueError):
                continue
            _permission_queue.put((rid, resp))
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
            resp = msg.get("response", {}) or {}
            try:
                rid = int(resp.get("request_id"))
            except (TypeError, ValueError):
                continue
            _permission_queue.put((rid, resp))
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

    try:
        sid = ensure_session(resume_id)
        if sid is None:
            return
        with _state_lock:
            _state["session"] = sid

        errors = apply_config(sid, cfg)
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
        agent_send({"jsonrpc": JSONRPC, "id": prompt_id, "method": "session/prompt",
                    "params": {"sessionId": sid, "prompt": content}})

        # Drive the turn: wait for the prompt response; while it runs, answer
        # permission requests as the user replies.
        turn_errors = list(errors)
        prompt_answer = None
        turn_deadline = time.monotonic() + float(os.environ.get("ACP_TURN_TIMEOUT", "300"))
        while True:
            if time.monotonic() > turn_deadline:
                agent_send({"jsonrpc": JSONRPC, "method": "session/cancel",
                            "params": {"sessionId": sid}})
                cancel_all_permissions()
                emit_result(sid, True, "", turn_errors + ["turn timed out"])
                return
            # Any pending permission the user answered?
            try:
                rid, resp = _permission_queue.get(timeout=0.1)
                # Find the matching permission request's offered options: the
                # request_id in control_response is the agent's rpc id; the
                # options were already sent to the UI. Resolve with the real
                # ones captured when the request went out.
                opts = _pending_permission_options.get(rid, [])
                option_id = resolve_permission(resp, opts)
                if option_id is None:
                    # No safe mapping: refuse rather than invent an id.
                    cancel_permission(rid)
                    turn_errors.append("permission %s: no matching option" % rid)
                    emit_result(sid, True, "", turn_errors)
                    return
                agent_send({"jsonrpc": JSONRPC, "id": rid,
                            "result": {"outcome": {"outcome": "chosen", "optionId": option_id}}})
                with _state_lock:
                    _pending_permissions.pop(rid, None)
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

            if _state["cancelled"]:
                # session/cancel sent; the agent may still answer the prompt.
                continue

        with _state_lock:
            _state["waiting"] = False
        if prompt_answer is None:
            emit_result(sid, True, "", turn_errors or ["no prompt response"])
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
            _state["config_options"] = config_options_from(result)
            _state["models"] = models_from(result)
            _state["current_model"] = current_model_from(result)
    except RpcError as e:
        emit_result("", True, "", ["cannot start session: %s" % e])
        return None
    if not sid:
        emit_result("", True, "", ["agent returned no session id"])
        return None
    return sid


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("usage: acp_bridge.py <agent-command...>\n")
        sys.exit(2)
    proc = subprocess.Popen(sys.argv[1:], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=None, text=True,
                            bufsize=1)
    _agent_proc[0] = proc
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
            proc.kill()


if __name__ == "__main__":
    main()
