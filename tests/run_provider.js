#!/usr/bin/env node
// Test harness: load the QML providers.js (minus the .pragma line) and call one
// descriptor member. argv: <fn> <json-arg>. Prints the result as JSON.
const fs = require("fs");
const path = require("path");

const src = fs.readFileSync(path.join(__dirname, "..", "providers.js"), "utf8")
    .replace(/^\.pragma[^\n]*\n/, "");
(0, eval)(src); // indirect eval: PROVIDERS lands in this scope

const fn = process.argv[2];
const arg = JSON.parse(process.argv[3] || "null");
let out;
if (fn === "kimi_caps") {
    out = {
        id: PROVIDERS.kimi.id,
        title: PROVIDERS.kimi.title,
        caps: PROVIDERS.kimi.caps,
        canUseTool: PROVIDERS.kimi.canUseTool,
        aliasModels: PROVIDERS.kimi.aliasModels,
        requiresKey: !!PROVIDERS.kimi.requiresKey,
    };
} else if (fn === "kimi_buildCommand") {
    out = PROVIDERS.kimi.buildCommand(Object.assign({
        q: (s) => "'" + String(s).replace(/'/g, "'\\''") + "'",
    }, arg));
} else if (fn === "kimi_parseLine") {
    out = PROVIDERS.kimi.parseLine(arg);
} else if (fn === "qoder_buildCommand") {
    out = PROVIDERS.qoder.buildCommand(Object.assign({
        q: (s) => "'" + String(s).replace(/'/g, "'\\''") + "'",
    }, arg));
} else if (fn === "qoder_caps") {
    out = {
        id: PROVIDERS.qoder.id,
        title: PROVIDERS.qoder.title,
        caps: PROVIDERS.qoder.caps,
        canUseTool: PROVIDERS.qoder.canUseTool,
        aliasModels: PROVIDERS.qoder.aliasModels,
        requiresKey: !!PROVIDERS.qoder.requiresKey,
    };
} else if (fn === "result_text") {
    out = resultText(arg.event, arg.lastText || "");
} else if (fn === "claude_buildCommand") {
    out = PROVIDERS.claude.buildCommand(Object.assign({
        q: (s) => "'" + String(s).replace(/'/g, "'\\''") + "'",
    }, arg));
} else if (fn === "cvc_buildCommand") {
    out = PROVIDERS.cvc.buildCommand(Object.assign({
        q: (s) => "'" + String(s).replace(/'/g, "'\\''") + "'",
    }, arg));
} else if (fn === "claude_caps" || fn === "cvc_caps") {
    const p = fn === "claude_caps" ? PROVIDERS.claude : PROVIDERS.cvc;
    out = {
        id: p.id,
        title: p.title,
        caps: p.caps,
        canUseTool: p.canUseTool,
        aliasModels: p.aliasModels,
        requiresKey: !!p.requiresKey,
        stdinUserFormat: p.stdinUserFormat ? p.stdinUserFormat("hi") : null,
    };
} else if (fn === "registry_buildCommand") {
    if (arg.data) setRegistry(arg.data);
    var d = byId(arg.id);
    out = d ? d.buildCommand(Object.assign({
        q: (s) => "'" + String(s).replace(/'/g, "'\\''") + "'",
    }, arg.opts || {})) : null;
} else if (fn === "registry_descriptor") {
    if (arg.data) setRegistry(arg.data);
    var rd = byId(arg.id);
    out = rd ? {
        id: rd.id, title: rd.title, adapter: rd.adapter, bridge: !!rd.bridge,
        caps: rd.caps, canUseTool: rd.canUseTool, aliasModels: rd.aliasModels,
        requiresKey: !!rd.requiresKey,
    } : null;
} else if (fn === "chipLabel") {
    out = chipLabel(arg.label, arg.max);
} else if (fn === "cancelMessage") {
    if (arg.data) setRegistry(arg.data);
    out = cancelMessage(byId(arg.id), arg.requestId || 7);
} else if (fn === "hintKey") {
    if (arg.data) setRegistry(arg.data);
    out = hintKey(byId(arg.id));
} else if (fn === "descriptor_flag") {
    out = !!(PROVIDERS[arg.id] && PROVIDERS[arg.id][arg.flag]);
} else if (fn === "keepsModel") {
    out = keepsModel(PROVIDERS[arg.provider], arg.models, arg.saved);
} else if (fn === "registry_set") {
    setRegistry(arg.data);
    const known = registryAll();
    out = {
        byId: {},
        unknownId: byId("no-such-provider") || null,
        allIds: known.map(function (p) { return p.id; }),
    };
    for (const id of out.allIds) {
        const p = byId(id);
        out.byId[id] = {
            id: p.id, title: p.title, adapter: p.adapter || null,
            baseUrl: p.baseUrl || "", command: p.command || "",
        };
    }
} else if (fn === "registry_parse") {
    setRegistry(arg.data);
    const p = byId(arg.id);
    out = p.parseLine(arg.line);
} else if (fn === "registry_command") {
    setRegistry(arg.data);
    const p = byId(arg.id);
    const q = (s) => "'" + String(s).replace(/'/g, "'\"'\"'") + "'";
    out = p ? {
        stdinUser: p.stdinUserFormat("hi"),
        cmd: p.buildCommand({ q: q, bridgeScript: "/bridges/acp_bridge.py" }),
        caps: p.caps,
    } : null;
} else {
    console.error("unknown fn " + fn);
    process.exit(2);
}
process.stdout.write(JSON.stringify(out));
