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
} else if (fn === "cc9_caps") {
    out = {
        id: PROVIDERS.cc9.id,
        title: PROVIDERS.cc9.title,
        caps: PROVIDERS.cc9.caps,
        canUseTool: PROVIDERS.cc9.canUseTool,
        aliasModels: PROVIDERS.cc9.aliasModels,
        requiresKey: !!PROVIDERS.cc9.requiresKey,
    };
} else if (fn === "cc9_buildCommand") {
    out = PROVIDERS.cc9.buildCommand(Object.assign({
        q: (s) => "'" + String(s).replace(/'/g, "'\\''") + "'",
    }, arg));
} else if (fn === "keepsModel") {
    out = keepsModel(PROVIDERS[arg.provider], arg.models, arg.saved);
} else {
    console.error("unknown fn " + fn);
    process.exit(2);
}
process.stdout.write(JSON.stringify(out));
