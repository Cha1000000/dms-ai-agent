pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    property string claudeModel: "haiku"
    property bool extendedThinking: false
    property string systemPrompt: "You are a concise desktop assistant on Linux with niri (Wayland compositor) and DankMaterialShell. " +
        "You have full tool access (Bash, Read, Write, Edit). Execute actions immediately, never ask for confirmation. " +
        "Respond in user's language. Be concise.\n\n" +
        "NIRI COMMANDS:\n" +
        "- List windows: niri msg -j windows\n" +
        "- Focus window by id: niri msg action focus-window --id ID\n" +
        "- Close focused window: niri msg action close-window\n" +
        "- Focus workspace: niri msg action focus-workspace N\n" +
        "- Move window to workspace: niri msg action move-window-to-workspace N\n" +
        "- Fullscreen: niri msg action fullscreen-window\n" +
        "- Maximize: niri msg action maximize-column\n" +
        "- Screenshot: niri msg action screenshot\n" +
        "- Toggle floating: niri msg action toggle-window-floating\n" +
        "- Focus left/right/up/down: niri msg action focus-column-left|right, focus-window-up|down\n" +
        "- Move column: niri msg action move-column-left|right\n" +
        "- Toggle overview: niri msg action toggle-overview\n\n" +
        "MUSIC: ~/go/bin/spogo (play, pause, next, prev, status, search track X, volume N)\n\n" +
        "Match fuzzy — 'brave' matches 'brave-browser-nightly', 'whatsapp' matches 'WhatsApp Web — Mozilla Firefox'.\n\n" +
        "IMPORTANT: When launching applications or running long-lived processes, ALWAYS detach them from the shell. " +
        "Use: setsid <command> >/dev/null 2>&1 & disown\n" +
        "NEVER run GUI apps in the foreground — always background and detach them.\n\n" +
        "Your working directory is a private state dir, not the user's home. " +
        "For user files always use ~ or absolute paths."

    // Set from the plugin settings (DmsAgent.qml).
    property int maxTokens: 1024
    property string pillLabel: "Jarvis"
    property string voiceModel: "auto"
    property string voiceLanguage: "auto"
    property string voiceVenv: ""

    property bool busy: false
    property string statusText: "Ready"
    property var messages: []
    property bool popoutVisible: false
    property string sessionId: ""
    property string lastCost: ""
    property var history: []

    signal messageAdded(var message)
    signal responseComplete()

    // --- Voice input ---
    // pw-record writes a 16 kHz mono WAV; voice.py sends it to a local
    // faster-whisper server that keeps the model loaded between phrases.
    // Stop uses SIGTERM: on SIGINT pw-record leaves a header-only file.
    property string voiceState: "idle"    // idle | recording | transcribing
    property int voiceSeconds: 0
    property string voiceError: ""
    signal voiceTextReady(string text)

    readonly property string voiceScript: decodeURIComponent(String(Qt.resolvedUrl("voice.py")).replace(/^file:\/\//, ""))
    readonly property string keybindScript: decodeURIComponent(String(Qt.resolvedUrl("keybind.sh")).replace(/^file:\/\//, ""))
    readonly property string voiceWav: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dms-agent-voice.wav"
    readonly property int voiceMaxSeconds: 120
    property var _recProcess: null
    property bool _recCancelled: false

    Component {
        id: recRunner
        Process {
            id: recProc
            command: ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", root.voiceWav]
            stderr: StdioCollector {}
            onExited: {
                if (root._recProcess === recProc) root._onRecordingExited();
                recProc.destroy();
            }
        }
    }

    Timer {
        id: voiceTicker
        interval: 1000; repeat: true
        running: root.voiceState === "recording"
        onTriggered: {
            root.voiceSeconds += 1;
            if (root.voiceSeconds >= root.voiceMaxSeconds) root.stopVoice();
        }
    }

    function startVoice() {
        if (busy || voiceState !== "idle") return;
        voiceError = "";
        voiceSeconds = 0;
        _recCancelled = false;
        var p = recRunner.createObject(root);
        _recProcess = p;
        p.running = true;
        voiceState = "recording";
    }

    function stopVoice() {
        if (voiceState !== "recording" || !_recProcess) return;
        voiceState = "transcribing";
        _recProcess.signal(15);
    }

    function cancelVoice() {
        if (voiceState !== "recording" || !_recProcess) return;
        _recCancelled = true;
        _recProcess.signal(15);
    }

    function _onRecordingExited() {
        _recProcess = null;
        if (_recCancelled || voiceState === "recording") {
            // Cancelled, or pw-record died on its own (no microphone, PipeWire down).
            if (!_recCancelled) voiceError = "Microphone unavailable";
            voiceState = "idle";
            runQuietExit("rm -f " + shellQuote(voiceWav), function() {});
            return;
        }
        var env = "DMS_AGENT_WHISPER_MODEL=" + shellQuote(voiceModel)
            + " DMS_AGENT_WHISPER_LANG=" + shellQuote(voiceLanguage)
            + " DMS_AGENT_WHISPER_VENV=" + shellQuote(voiceVenv) + " ";
        runQuietExit(env + "python3 " + shellQuote(voiceScript) + " transcribe " + shellQuote(voiceWav)
                + "; rm -f " + shellQuote(voiceWav), function(output) {
            var result = {};
            try { result = JSON.parse(String(output).trim()); } catch(e) { result = { error: "No response from speech recognition" }; }
            if (result.error) voiceError = result.error;
            else if (!result.text) voiceError = "No speech recognized";
            else voiceTextReady(result.text);
            voiceState = "idle";
        });
    }

    // --- Hotkey ---
    // niri binds live in the compositor config, so the setting is written to a
    // small include file by keybind.sh. Applied only when the setting was
    // actually set, otherwise the file install.sh created is left alone.
    property var _appliedHotkey: null

    function applyHotkey(key) {
        if (key === _appliedHotkey) return;
        _appliedHotkey = key;
        run(shellQuote(keybindScript) + " " + shellQuote(key) + " 2>&1", function(output) {
            var text = String(output).trim();
            if (text !== "" && !/^hotkey:/m.test(text))
                runQuietExit("notify-send -a 'DMS AI Agent' 'Hotkey not applied' " + shellQuote(text.substring(0, 200)), function() {});
        });
    }

    // --- Chat panel across monitors ---
    // One widget instance per bar; only one chat panel is visible at a time.
    // panelRequested("*") means "any monitor": the first instance to react wins.
    signal panelRequested(string screenName)
    signal panelHideRequested()
    property string visibleScreen: ""

    function setPanelVisible(name, isVisible) {
        if (isVisible) visibleScreen = name;
        else if (visibleScreen === name) visibleScreen = "";
        popoutVisible = visibleScreen !== "";
    }
    function showPanelOn(name) {
        panelRequested(name);
    }

    // Keybinding entry point: open on the monitor that has focus.
    IpcHandler {
        target: "dmsAgent"
        function toggle(): string {
            if (root.visibleScreen !== "") {
                root.panelHideRequested();
                return "closed";
            }
            root.runQuietExit("niri msg -j focused-output 2>/dev/null", function(output) {
                var name = "";
                try { name = JSON.parse(String(output)).name || ""; } catch(e) {}
                if (name) root.showPanelOn(name);
                // No pill on the focused monitor (or niri unavailable): open anywhere.
                if (root.visibleScreen === "") root.showPanelOn("*");
            });
            return "opened";
        }
    }

    readonly property string homeDir: Quickshell.env("HOME") || ""
    // Agent sessions live in their own Claude Code project (a slug of this dir),
    // apart from interactive sessions started in $HOME. history.py relies on it
    // too, so both are launched from here.
    readonly property string workDir: homeDir + "/.local/state/dms-agent"
    readonly property string cdWorkDir: "mkdir -p " + shellQuote(workDir) + " && cd " + shellQuote(workDir) + " && "

    Component.onCompleted: { loadHistory(); }

    // --- Process runner ---
    Component {
        id: cmdRunner
        Process {
            id: cmdProc
            property string shellCmd: ""
            property var onFinished: null
            command: ["bash", "-lc", shellCmd]
            stdout: StdioCollector {
                onStreamFinished: { if (cmdProc.onFinished) cmdProc.onFinished(text); }
            }
            stderr: StdioCollector {}
            onExited: { cmdProc.destroy(); }
        }
    }

    function run(shellCmd, cb) {
        var p = cmdRunner.createObject(root, { shellCmd: shellCmd, onFinished: cb });
        p.running = true;
        return p;
    }

    function runQuietExit(shellCmd, cb) {
        var body = String(shellCmd).replace(/;+\s*$/, "").trim();
        return run((body ? body + "; " : "") + "exit 0", cb);
    }

    function shellQuote(input) {
        return "'" + String(input).replace(/'/g, "'\"'\"'") + "'";
    }

    // --- Messages ---
    function addMessage(role, content) {
        var msg = { role: role, content: content, timestamp: Date.now() };
        var newMessages = messages.slice();
        newMessages.push(msg);
        messages = newMessages;
        messageAdded(msg);
        return msg;
    }

    function clearMessages() {
        messages = [];
        sessionId = "";
        lastCost = "";
    }

    // --- Notification ---
    function notifyIfHidden(text) {
        if (popoutVisible) return;
        runQuietExit("notify-send -a 'DMS Agent' -i smart_toy 'Agent' " + shellQuote(String(text).substring(0, 100)), function() {});
    }

    // --- History (reads from Claude CLI session files) ---
    // Resolved next to this file: the plugin directory name depends on how it was installed.
    readonly property string historyScript: decodeURIComponent(String(Qt.resolvedUrl("history.py")).replace(/^file:\/\//, ""))

    function loadHistory() {
        runQuietExit(cdWorkDir + "python3 " + shellQuote(historyScript) + " list", function(output) {
            try { history = JSON.parse(String(output).trim()); } catch(e) { history = []; }
        });
    }

    function resumeSession(historySessionId) {
        if (busy) return;
        sessionId = historySessionId;
        messages = [];
        busy = true;
        statusText = "Loading session...";

        runQuietExit(cdWorkDir + "python3 " + shellQuote(historyScript) + " restore " + shellQuote(historySessionId), function(output) {
            var loaded = [];
            try { loaded = JSON.parse(String(output).trim()); } catch(e) {}
            for (var i = 0; i < loaded.length; i++) {
                loaded[i].timestamp = Date.now();
                var newMsgs = messages.slice();
                newMsgs.push(loaded[i]);
                messages = newMsgs;
                messageAdded(loaded[i]);
            }
            if (loaded.length === 0) {
                addMessage("assistant", "Session resumed.");
            }
            busy = false;
            statusText = "Ready";
        });
    }

    // --- Intent detection ---
    readonly property var goToPatterns: [
        /^(?:go\s*to|switch\s*to|llévame\s*a|llevame\s*a|ir\s*a|ve\s*a|muéstrame|muestrame|cambiar?\s*a|navegar?\s*a|show\s*me)\s+(.+)/i
    ]
    readonly property var closePatterns: [
        /^(?:close|cierra|kill|mata|termina|quit|exit)\s+(.+)/i
    ]
    readonly property var openPatterns: [
        /^(?:open|abre|launch|lanza|ejecuta|run|start|inicia)\s+(.+)/i
    ]

    function detectIntent(text) {
        var t = text.trim();
        for (var i = 0; i < goToPatterns.length; i++) { var m = t.match(goToPatterns[i]); if (m) return { intent: "goto", target: m[1].trim() }; }
        for (var j = 0; j < closePatterns.length; j++) { var m2 = t.match(closePatterns[j]); if (m2) return { intent: "close", target: m2[1].trim() }; }
        for (var k = 0; k < openPatterns.length; k++) { var m3 = t.match(openPatterns[k]); if (m3) return { intent: "open", target: m3[1].trim() }; }
        return null;
    }

    // --- Send message ---
    function sendMessage(text) {
        if (busy || !text.trim()) return;
        addMessage("user", text);
        busy = true;

        var intent = detectIntent(text);
        if (intent) {
            prefetchContext(intent, function(ctx) { callClaude(text + "\n" + ctx); });
        } else {
            statusText = "Thinking...";
            callClaude(text);
        }
    }

    // --- Pre-fetch context ---
    function prefetchContext(intent, callback) {
        if (intent.intent === "goto") {
            statusText = "Scanning windows...";
            runQuietExit("niri msg -j windows 2>/dev/null", function(output) {
                var windows; try { windows = JSON.parse(output); } catch(e) { windows = []; }
                var summary = windows.map(function(w) {
                    return "id:" + w.id + " app:" + w.app_id + " title:\"" + w.title + "\"" + (w.is_focused ? " (focused)" : "");
                }).join("\n");
                callback("[Open windows]\n" + summary);
            });
        } else if (intent.intent === "close") {
            statusText = "Scanning processes...";
            runQuietExit("ps aux | grep -iv grep | grep -i " + shellQuote(intent.target) + " | head -10", function(output) {
                callback("[Matching processes]\n" + String(output).trim());
            });
        } else if (intent.intent === "open") {
            statusText = "Searching apps...";
            var q = intent.target.toLowerCase();
            var cmd = "for dir in /usr/share/applications /usr/local/share/applications \"$HOME/.local/share/applications\"; do "
                + "[ -d \"$dir\" ] || continue; grep -ril " + shellQuote(q) + " \"$dir\"/*.desktop 2>/dev/null; done "
                + "| while read f; do name=$(grep -m1 '^Name=' \"$f\" | cut -d= -f2); "
                + "exec=$(grep -m1 '^Exec=' \"$f\" | cut -d= -f2 | sed 's/ %[a-zA-Z]//g'); "
                + "echo \"$name | cmd: $exec\"; done | head -10";
            runQuietExit(cmd, function(output) {
                callback("[Matching apps]\n" + String(output).trim());
            });
        } else {
            callback("");
        }
    }

    // --- Claude process ---
    // Output is read as stream-json, one event per line, so every tool call
    // shows up in the chat while the agent is still working.
    property var _claudeProcess: null
    property bool _gotResult: false
    property string _lastText: ""
    property var _toolNames: ({})

    Component {
        id: claudeRunner
        Process {
            id: claudeProc
            property string shellCmd: ""
            command: ["bash", "-lc", shellCmd]
            stdout: SplitParser {
                onRead: data => {
                    if (root._claudeProcess === claudeProc) root.handleStreamLine(data);
                }
            }
            stderr: StdioCollector {}
            onExited: {
                if (root._claudeProcess === claudeProc) exitGrace.restart();
                // Delayed: stdout lines may still be in flight when the exit arrives.
                claudeProc.destroy(2000);
            }
        }
    }

    // Process ended without a "result" event (crash, no network, killed from outside).
    Timer {
        id: exitGrace
        interval: 700
        onTriggered: {
            if (root._claudeProcess && !root._gotResult) {
                root._claudeProcess = null;
                root.finishResponse(root._lastText || "(error: agent exited without a response)");
            }
        }
    }

    function cancelRequest() {
        if (_claudeProcess) {
            _claudeProcess.signal(15);
            _claudeProcess = null;
            busy = false;
            statusText = "Ready";
        }
    }

    function callClaude(prompt) {
        statusText = extendedThinking ? "Thinking..." : "Processing...";
        _gotResult = false;
        _lastText = "";
        _toolNames = ({});

        // exec: bash is replaced by claude, so Cancel's SIGTERM reaches claude itself.
        var cmd = cdWorkDir + "exec claude -p"
            + " --model " + shellQuote(claudeModel)
            + " --output-format stream-json --verbose"
            + " --dangerously-skip-permissions"
            + " --append-system-prompt " + shellQuote(systemPrompt)
            + (sessionId ? " --resume " + shellQuote(sessionId) : "")
            + " 2>/dev/null <<< " + shellQuote(prompt);

        var p = claudeRunner.createObject(root, { shellCmd: cmd });
        _claudeProcess = p;
        p.running = true;
    }

    function handleStreamLine(line) {
        var ev;
        try { ev = JSON.parse(line); } catch(e) { return; }

        var content = ev.message && Array.isArray(ev.message.content) ? ev.message.content : [];

        if (ev.type === "assistant") {
            for (var i = 0; i < content.length; i++) {
                var block = content[i];
                if (block.type === "thinking") {
                    statusText = "Thinking...";
                } else if (block.type === "tool_use") {
                    var newNames = Object.assign({}, _toolNames);
                    newNames[block.id] = block.name;
                    _toolNames = newNames;
                    var step = describeTool(block.name, block.input);
                    addMessage("tool_status", step);
                    statusText = step;
                } else if (block.type === "text" && block.text) {
                    _lastText = block.text;
                    statusText = "Writing answer...";
                }
            }
        } else if (ev.type === "user") {
            for (var j = 0; j < content.length; j++) {
                var res = content[j];
                if (res.type !== "tool_result") continue;
                if (res.is_error) {
                    addMessage("tool_status", "✗ " + (_toolNames[res.tool_use_id] || "tool") + " failed");
                }
                statusText = extendedThinking ? "Thinking..." : "Processing...";
            }
        } else if (ev.type === "result") {
            _gotResult = true;
            _claudeProcess = null;
            handleResult(ev);
        }
    }

    // One line per tool call: name plus the most telling argument.
    function describeTool(name, input) {
        var inp = input || {};
        var arg = inp.command || inp.file_path || inp.path || inp.pattern || inp.url || inp.query || inp.description || "";
        if (!arg) {
            try { arg = JSON.stringify(inp); } catch(e) { arg = ""; }
            if (arg === "{}") arg = "";
        }
        arg = String(arg).replace(/\s+/g, " ").trim();
        if (homeDir) arg = arg.split(homeDir).join("~");
        if (arg.length > 120) arg = arg.substring(0, 117) + "...";
        return arg ? name + ": " + arg : name;
    }

    function handleResult(data) {
        if (data.session_id) sessionId = data.session_id;

        lastCost = "";
        if (data.total_cost_usd !== undefined) {
            lastCost = "$" + data.total_cost_usd.toFixed(4);
        }
        if (data.usage) {
            var inp = data.usage.input_tokens || 0;
            var out = data.usage.output_tokens || 0;
            lastCost += " (" + inp + "→" + out + " tokens)";
        }

        var response = data.result || _lastText || "";
        finishResponse(response || "(done)");
        loadHistory();
    }

    function finishResponse(text) {
        addMessage("assistant", text);
        busy = false; statusText = "Ready";
        responseComplete(); notifyIfHidden(text);
    }
}
