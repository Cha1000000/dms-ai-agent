.pragma library

// Provider registry for DMS Agent. The plugin keeps its internal event stream
// in the claude stream-json shape; every provider is a descriptor here that
// knows how to build its command line and translate its own output back into
// that shape. Adding a provider means adding one descriptor — nothing else in
// the plugin learns its CLI's name.
//
// Descriptor fields:
//   id, title
//   caps: { askFirst, cost, stdinEnabled, cancelViaStdin, perSessionRestore,
//           registryHistory }
//   buildCommand(opts) -> shell command string (cdWorkDir is prepended by the caller)
//   stdinUserFormat(text) -> object to write on stdin (null if caps.stdinEnabled is false)
//   parseLine(line) -> array of canonical events (empty if the line is noise)
//   canUseTool: true when the provider speaks the can_use_tool protocol
//   aliasModels: true when --model also takes the bare "opus"-style aliases
//   requiresKey: true when the CLI needs a key from providers.json (see provider_secrets.py)
// Model lists and effort levels come from models.py. registryHistory marks a
// provider whose transcripts cannot be scanned for "sessions this chat
// started" (they look the same as the user's own TUI runs): the Jarvis session
// registry is then the history, and each session id is registered the moment
// its "result" event arrives.
//
// An attachment goes to the agent as the path to the file, and the agent
// opens it with its own tools: nothing here streams an image into the model,
// so there is no vision flag to set.

var PROVIDERS = {};

PROVIDERS.claude = {
    id: "claude",
    title: "Claude Code",
    caps: {
        askFirst: true,
        cost: true,
        stdinEnabled: true,
        cancelViaStdin: true,
        perSessionRestore: true
    },

    // opts: { model, effort, confirm, systemPrompt, prompt, resumeId, cli }
    buildCommand: function (opts) {
        var confirm = !!opts.confirm;
        // The prompt always comes through stdin, never as an argument and never
        // as a heredoc: stdin is the channel the Cancel button needs. The CLI
        // stops the current turn on a control_request/interrupt, and it only
        // reads that from a live pipe — with the prompt in a heredoc the stdin
        // is already closed and the interrupt never arrives.
        var cmd = "DMS_AGENT=1 exec " + (opts.cli || "claude") + " -p"
            + " --model " + opts.q(opts.model)
            + (opts.effort ? " --effort " + opts.q(opts.effort) : "")
            + " --input-format stream-json"
            + (confirm ? " --permission-mode default --permission-prompt-tool stdio"
                       : "")
            + " --output-format stream-json --verbose"
            + (confirm ? "" : " --dangerously-skip-permissions")
            + " --append-system-prompt " + opts.q(opts.systemPrompt)
            + (opts.resumeId ? " --resume " + opts.q(opts.resumeId) : "")
            + " 2>/dev/null";
        return cmd;
    },

    stdinUserFormat: function (text) {
        return { type: "user", message: { role: "user", content: text } };
    },

    // The claude stream is already the canonical shape: hand it through.
    parseLine: function (line) {
        try {
            return [JSON.parse(line)];
        } catch (e) {
            return [];
        }
    },

    canUseTool: true,
    // The CLI takes bare "opus"-style aliases next to full ids, so a saved alias
    // that the catalog does not list is still a valid choice here.
    aliasModels: true,
};
// CheapVibeCode is the stock claude CLI pointed at their gateway
// (ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN from providers.json). The gateway
// rejects the bare "haiku"-style aliases, so --model is always a full id from
// GET /v1/models (see models.py). Ask-first is not confirmed on that gateway —
// the can_use_tool handshake stalls — so the chat runs unattended, like Qoder.
PROVIDERS.cvc = {
    id: "cvc",
    title: "CheapVibeCode",
    caps: {
        askFirst: false,
        cost: true,
        stdinEnabled: true,
        cancelViaStdin: true,
        perSessionRestore: true
    },

    buildCommand: function (opts) {
        // Token comes from providers.json at launch, never through plugin
        // settings (ccsync syncs those). provider_secrets prints it as JSON and
        // python sets the env before exec'ing claude.
        var envCmd = "eval $(python3 " + opts.q(opts.secretsScript)
            + " env-export cvc) && ";
        return envCmd + PROVIDERS.claude.buildCommand(opts);
    },

    stdinUserFormat: PROVIDERS.claude.stdinUserFormat,
    parseLine: PROVIDERS.claude.parseLine,
    canUseTool: false,
    requiresKey: true,
};
// 9Router (cc9) is the stock claude CLI run through the cc9 wrapper: the CLI
// pointed at the local 9Router gateway, with its own config dir. It is a
// separate provider because the gateway catalog is only visible when that
// wrapper is used: DMS started from systemd inherits no cc9 environment, so
// the stock CLI on PATH reports the five native Claude models instead of the
// gateway's aggregate. The wrapper speaks the same protocol (checked live
// 2026-11-03: the can_use_tool handshake and the --model ids both work), so
// the only difference is the binary that is run and the catalog it reports.
PROVIDERS.cc9 = {
    id: "cc9",
    title: "9Router (cc9)",
    caps: {
        askFirst: true,
        cost: true,
        stdinEnabled: true,
        cancelViaStdin: true,
        perSessionRestore: true
    },

    buildCommand: function (opts) {
        return PROVIDERS.claude.buildCommand(Object.assign({}, opts, {cli: "cc9"}));
    },

    stdinUserFormat: PROVIDERS.claude.stdinUserFormat,
    parseLine: PROVIDERS.claude.parseLine,
    canUseTool: true,
    // The gateway's own presets: the bare aliases resolve to the Combo, and
    // the Combo must not be in Jarvis.
    aliasModels: false,
};
// Qoder is its own CLI (qodercli). The query is a positional argument (not
// stdin), the stream is the claude stream-json shape nearly as-is, and
// ask-first is impossible in print mode (--permission-prompt-tool conflicts
// with stream-json input), so the chat always runs unattended. Models are the
// flat --list-models column and effort is --reasoning-effort (models.py).
PROVIDERS.qoder = {
    id: "qoder",
    title: "Qoder",
    caps: {
        askFirst: false,
        cost: false,
        stdinEnabled: false,
        cancelViaStdin: false,
        perSessionRestore: true,
        registryHistory: true
    },

    buildCommand: function (opts) {
        // The user's MCP servers are declared for the other harnesses; this run
        // starts none, so a chat does not spawn seven helpers it will never use.
        return "exec qodercli --output-format stream-json"
            + " --dangerously-skip-permissions"
            + " --mcp-config " + opts.q('{"mcpServers":{}}')
            + " --strict-mcp-config"
            + " --model " + opts.q(opts.model)
            + (opts.effort ? " --reasoning-effort " + opts.q(opts.effort) : "")
            + " --append-system-prompt " + opts.q(opts.systemPrompt)
            + (opts.resumeId ? " --resume " + opts.q(opts.resumeId) : "")
            + " -p -- " + opts.q(opts.prompt)
            + " 2>/dev/null";
    },

    stdinUserFormat: null,
    parseLine: PROVIDERS.claude.parseLine,
    canUseTool: false,
    // The catalog is full ids only ("Qwen3.8-Flash"): a bare alias saved from
    // another provider is replaced by the picker's fallback.
    aliasModels: false,
};

// Kimi Code is its own CLI. The query is a -p argument, and it has no
// --append-system-prompt — the system prompt goes in front of the user text in
// that one argument. Output is its own stream-json shape (five record kinds),
// duplicated on stderr, so only stdout is read. Effort is an env var
// (KIMI_MODEL_THINKING_EFFORT), models are the full config keys from
// ~/.kimi-code/config.toml (models.py), resume is --session. Its transcripts
// cannot be told apart from the user's own TUI runs (registryHistory). The
// session state carries no model, but the wire log does (profile.bind), so the
// model and effort of a run come back on restore (perSessionRestore: true).
PROVIDERS.kimi = {
    id: "kimi",
    title: "Kimi Code",
    caps: {
        askFirst: false,
        cost: false,
        stdinEnabled: false,
        cancelViaStdin: false,
        perSessionRestore: true,
        registryHistory: true
    },

    buildCommand: function (opts) {
        // --auto (Never Ask) cannot be combined with --prompt — the CLI rejects
        // the pair ("Cannot combine --prompt with --auto", kimi 2.4.1). Print
        // mode runs unattended on its own: tools execute without a dialog.
        // Kimi has no --mcp-config flag and always reads <KIMI_CODE_HOME>/mcp.json,
        // so the run gets a home whose only difference is an empty MCP file: the
        // login, config and sessions are symlinked back. That keeps the seven
        // servers the other harnesses need out of every chat (measured: +8
        // processes and ~20 s on the first run without it).
        return "KIMI_HOME=" + opts.q(opts.stateDir + "/kimi-home") + " && "
            + "mkdir -p \"$KIMI_HOME\" && (cd \"$KIMI_HOME\" && "
            + "for f in credentials oauth device_id region config.toml AGENTS.md tui.toml "
            + "sessions session_index.jsonl migrations-effort.json; do "
            + "[ -e \"$HOME/.kimi-code/$f\" ] && ln -sfn \"$HOME/.kimi-code/$f\" \"$f\"; done; "
            + "printf '{\"mcpServers\": {}}' > mcp.json) && "
            + (opts.effort ? "KIMI_MODEL_THINKING_EFFORT=" + opts.q(opts.effort) + " " : "")
            + "KIMI_CODE_HOME=\"$KIMI_HOME\" exec kimi --output-format stream-json"
            + " --model " + opts.q(opts.model)
            + (opts.resumeId ? " --session " + opts.q(opts.resumeId) : "")
            + " -p " + opts.q(opts.systemPrompt + "\n\n" + opts.prompt)
            + " 2>/dev/null";
    },

    stdinUserFormat: null,

    parseLine: function (line) {
        var d;
        try {
            d = JSON.parse(line);
        } catch (e) {
            return [];
        }
        if (d.role === "meta") {
            if (d.type === "session.resume_hint" && d.session_id)
                return [{ type: "result", session_id: d.session_id }];
            return [];
        }
        if (d.role === "assistant") {
            var content = [];
            if (typeof d.content === "string" && d.content)
                content.push({ type: "text", text: d.content });
            else if (Array.isArray(d.content)) {
                for (var i = 0; i < d.content.length; i++) {
                    var c = d.content[i];
                    if (c.type === "text" && c.text)
                        content.push({ type: "text", text: c.text });
                    else if (c.type === "think" && c.think)
                        content.push({ type: "thinking", thinking: c.think });
                }
            }
            if (Array.isArray(d.tool_calls)) {
                for (var j = 0; j < d.tool_calls.length; j++) {
                    var tc = d.tool_calls[j];
                    var input = {};
                    try {
                        input = JSON.parse(tc.function.arguments);
                    } catch (e) {}
                    content.push({ type: "tool_use", id: tc.id, name: tc.function.name, input: input });
                }
            }
            return content.length ? [{ type: "assistant", message: { content: content } }] : [];
        }
        if (d.role === "tool") {
            return [{ type: "user", message: { content: [
                { type: "tool_result", tool_use_id: d.tool_call_id, content: d.content }
            ] } }];
        }
        return [];
    },

    canUseTool: false,
    // Full config keys only ("kimi-code/k3.1-pro"): a bare alias saved from
    // another provider is replaced by the picker's fallback.
    aliasModels: false,
};

// Text of a "result" event for the chat bubble. A run that ends without an
// answer carries its reason in `errors[]` (claude does this for an unresumed
// session: "No conversation found with session ID: …"), and printing nothing
// there told the user "(done)" for a run that had plainly failed (caught live
// 2026-11-02). Empty means a run that really finished with nothing to say.
function resultText(ev, lastText) {
    if (!ev) return lastText || "";
    if (ev.is_error) {
        var errs = Array.isArray(ev.errors) ? ev.errors.filter(function (e) { return !!e; }) : [];
        if (errs.length) return "Error: " + errs.join("; ");
        var raw = typeof ev.result === "string" ? ev.result.trim() : "";
        return raw ? ev.result : "Error: the agent ended the run without an answer";
    }
    return ev.result || lastText || "";
}

function byId(id) {
    // No fallback to claude: a deleted or mistyped provider id must be visible
    // to the caller (AgentService guards on it), never silently substituted.
    if (!id) return PROVIDERS.claude; // the default, not a substitution
    return _registryDescriptors[id] || PROVIDERS[id] || undefined;
}

function all() {
    return Object.keys(PROVIDERS).map(function (k) { return PROVIDERS[k]; });
}

// --- Providers from providers.json (the external registry) ------------------
// Loaded by AgentService.qml through registry.py (a Process, not here: a
// .pragma library cannot run a program). setRegistry() replaces the previous
// dynamic set in one go; the builtin five are never touched.
var _registryDescriptors = {};

function setRegistry(data) {
    _registryDescriptors = {};
    var providers = (data && data.providers) || {};
    for (var id in providers) {
        if (!providers.hasOwnProperty(id)) continue;
        var entry = providers[id];
        if (!entry || typeof entry !== "object" || !entry.adapter) continue;
        if (!/^[a-z0-9-]+$/.test(id)) continue; // same rule as registry.py
        if (entry.adapter !== "acp" && entry.adapter !== "codex" && entry.adapter !== "openai") continue;
        _registryDescriptors[id] = {
            id: id,
            title: String(entry.title || id),
            adapter: entry.adapter,
            command: entry.command || "",
            baseUrl: entry.baseUrl || "",
            caps: {
                askFirst: false,
                cost: false,
                stdinEnabled: true,
                // The bridges read a {"type":"cancel"} line and end the turn
                // with an error result — the interrupt the claude CLI speaks
                // is not part of their protocol.
                cancelViaStdin: true,
                perSessionRestore: true,
                registryHistory: true
            },
            // The prompt goes to the bridge's stdin (config line is prepended
            // by the service); it never appears in argv or logs.
            stdinUserFormat: function (text) {
                return { type: "user", message: { role: "user",
                         content: [{ type: "text", text: String(text) }] } };
            },
            buildCommand: function (opts) {
                // The bridge is the executed program; the provider's agent
                // command is its argument, quoted element by element. The
                // openai adapter takes the base URL instead of a command.
                var bridge = opts.bridgeScript || "";
                if (!bridge) return "exit 3";
                var args;
                if (this.adapter === "openai") {
                    if (!this.baseUrl) return "exit 3";
                    args = [this.baseUrl];
                } else {
                    args = Array.isArray(this.command) ? this.command
                        : String(this.command).split(/\s+/).filter(Boolean);
                    if (!args.length) return "exit 3";
                }
                var env = this.adapter === "openai" ? "DMS_AGENT_OPENAI_PROVIDER=" + opts.q(this.id) + " " : "";
                return env + "exec python3 " + opts.q(bridge) + " "
                    + args.map(opts.q).join(" ") + " 2>/dev/null";
            },
            parseLine: PROVIDERS.claude.parseLine,
            canUseTool: false,
            aliasModels: false,
        };
    }
}

function registryAll() {
    var ids = Object.keys(_registryDescriptors);
    return all().concat(ids.map(function (k) { return _registryDescriptors[k]; }));
}

// The name in the chat's chip: the bare model name, cut to a length the chip
// can show. A gateway lists the vendor in front of the name ("OpenAI · GPT 6
// Astra"), and the whole name pushed the buttons on the toolbar row out of
// the window. The picker keeps the full name; the chip shows the model.
function chipLabel(label, max) {
    var text = String(label === undefined || label === null ? "" : label).trim();
    if (!text) return "";
    var sep = text.indexOf("·");
    if (sep >= 0) text = text.slice(sep + 1).trim();
    var limit = max || 18;
    if (text.length <= limit) return text;
    return text.slice(0, limit - 1).replace(/\s+$/, "") + "…";
}

// Whether a saved model id still fits the catalog that was just fetched.
// The id survives when the catalog offers it — by its id or by the model it
// resolves to. A bare alias ("opus") survives only while the catalog still
// lists the aliases: a harness aggregate (cc9 + 9Router) has none, and there
// "opus" is the Combo, which must not be in Jarvis. Live 2026-11-03: with the
// aggregate in the picker a leftover id of another provider ("kimi-k2.8-preview")
// looked like an alias (letters and dashes only) and kept the picker stuck on
// a model the CLI would reject.
function keepsModel(provider, models, saved) {
    if (!saved) return false;
    var list = models || [];
    for (var i = 0; i < list.length; i++) {
        var m = list[i];
        if (m.id === saved || (m.resolved && m.resolved === saved)) return true;
    }
    var aliasesOffered = list.some(function (m) {
        return m.id === "opus" || m.id === "sonnet" || m.id === "haiku";
    });
    return !!(provider && provider.aliasModels) && aliasesOffered
        && /^[a-z0-9-]+$/i.test(saved);
}
