pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io
import "i18n.js" as I18n
import "providers.js" as Providers

Singleton {
    id: root

    // Interface language. The Language setting is about speech recognition, but
    // someone who fixes it to their own language means the plugin to speak it —
    // so it drives the interface too. Left on "auto" it follows the locale.
    readonly property string uiLanguage: {
        var lang = (voiceLanguage && voiceLanguage !== "auto") ? voiceLanguage : "";
        if (!lang) {
            var env = Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES") || Quickshell.env("LANG") || "";
            lang = String(env).substring(0, 2);
        }
        return String(lang).toLowerCase();
    }

    function tr(key, args) {
        return I18n.t(uiLanguage, key, args);
    }

    property string claudeModel: "haiku"

    // The model picked for each provider, keyed by provider id. Switching
    // providers swaps catalogs: a model id from one ("Qwen3.8-Flash") is
    // rejected by another's --model, so each keeps its own choice.
    property var providerModels: ({})
    // The settings page writes claudeModel directly, so the map follows every
    // change — not only the ones made through chooseModel().
    onClaudeModelChanged: syncProviderModel()
    function syncProviderModel() {
        if (providerModels[providerId] === claudeModel) return;
        var map = {};
        for (var k in providerModels) map[k] = providerModels[k];
        map[providerId] = claudeModel;
        providerModels = map;
        // The map is a local here on purpose: saving reloads the settings into
        // these properties (DmsAgent.qml), which replaces providerModels.
        settingChosen("providerModels", map);
    }

    // The /model list of the CLI (minus Fable), filled by models.py so new
    // versions and names appear on their own. Until it answers, the bare aliases
    // are offered — they always point at the latest version anyway.
    property var models: [
        { id: "opus", label: "Opus", resolved: "" },
        { id: "sonnet", label: "Sonnet", resolved: "" },
        { id: "haiku", label: "Haiku", resolved: "" }
    ]
    readonly property string modelsScript: decodeURIComponent(String(Qt.resolvedUrl("models.py")).replace(/^file:\/\//, ""))
    readonly property string secretsScript: decodeURIComponent(String(Qt.resolvedUrl("provider_secrets.py")).replace(/^file:\/\//, ""))
    property double _modelsFetchedAt: 0
    // Which provider the `models` list belongs to. A switch swaps catalogs, and
    // until the new one arrives `cliModel` still resolves through the old list:
    // sending then would pass a foreign model id to the new CLI.
    property string _modelsProvider: ""
    // Set when the provider's model catalog could not be read: the picker
    // shows the reason instead of another provider's models.
    property string modelsError: ""

    // A model is selected either by its alias ("opus") or by a full id
    // ("claude-opus-4-7"), so both have to be matched.
    function isCurrentModel(m) {
        return claudeModel === m.id || (m.resolved !== "" && claudeModel === m.resolved);
    }

    // Short captions for the current flagship of each family (the alias entries);
    // the CLI's own descriptions are English and too long for the dropdown.
    function modelDesc(m) {
        const keys = { opus: "model.best", sonnet: "model.balanced", haiku: "model.fast" };
        return keys[m.id] ? tr(keys[m.id]) : "";
    }

    function modelLabel(id) {
        const m = models.find(x => x.id === id || (x.resolved !== "" && x.resolved === id));
        return m ? m.label : id;
    }

    // The name in the chat's chip: the bare model name, cut to what fits.
    // A gateway lists the vendor in front of the name ("OpenAI · GPT 6
    // Astra"), and the whole name pushed the buttons out of the window.
    function chipLabel(id) {
        return Providers.chipLabel(modelLabel(id), 18);
    }

    // Where the chosen model sits in the catalog — the picker scrolls to it.
    // -1 when the catalog does not list it.
    function currentModelIndex() {
        for (let i = 0; i < models.length; i++) {
            if (isCurrentModel(models[i])) return i;
        }
        return -1;
    }

    // At most once an hour: the CLI updates itself while the shell keeps running.
    function refreshModels() {
        if (Date.now() - _modelsFetchedAt < 3600000) return;
        _modelsFetchedAt = Date.now();
        const wanted = providerId;
        run(cdWorkDir + "python3 " + shellQuote(modelsScript) + " --provider " + shellQuote(wanted) + " 2>/dev/null", function(output) {
            // A switch to another provider while the request was in flight leaves
            // this answer stale — the newer call owns the list now.
            if (wanted !== providerId) return;
            try {
                const list = JSON.parse(output);
                if (Array.isArray(list) && list.length > 0) {
                    models = list;
                    modelsError = "";
                    _modelsProvider = wanted;
                    // A saved id left from another provider ("opus",
                    // "Qwen3.8-Flash") would be rejected by --model. It survives
                    // only when the new catalog still lists it (or the aliases
                    // it can still resolve) — providers.keepsModel() decides.
                    if (!Providers.keepsModel(provider, models, String(claudeModel))) {
                        const hint = String(claudeModel).toLowerCase();
                        const byHint = models.find(x => hint && String(x.id).toLowerCase().indexOf(hint) >= 0);
                        const first = models.find(x => String(x.id).indexOf("group") < 0) || models[0];
                        chooseModel((byHint && String(byHint.id).indexOf("group") < 0 ? byHint : first).id);
                    }
                } else {
                    // The provider's catalog is empty or unreachable: the picker
                    // must not keep showing another provider's models as if
                    // they were this one's.
                    models = [];
                    modelsError = tr("models.unavailable");
                    _modelsProvider = wanted;
                    _modelsFetchedAt = 0;
                }
            } catch (e) {
                models = [];
                modelsError = tr("models.unavailable");
                _modelsProvider = wanted;
                _modelsFetchedAt = 0;
            }
        });
    }

    // Reasoning effort passed as --effort. Empty means "auto": no flag, the CLI
    // picks its own default. Only levels the current model supports are valid.
    property string effort: ""
    readonly property var effortLevels: {
        const m = models.find(x => x.id === claudeModel || (x.resolved && x.resolved === claudeModel));
        return (m && m.efforts) ? m.efforts : [];
    }
    readonly property string activeEffort: effortLevels.indexOf(effort) >= 0 ? effort : ""
    // What goes to --model: the full id the picker resolved, not the alias. The CLI does not
    // always honour the alias: `--model haiku` ran claude-sonnet-5-5 on 2.1.306.
    readonly property string cliModel: {
        const m = models.find(x => x.id === claudeModel);
        return (m && m.resolved) ? m.resolved : claudeModel;
    }
    // "confirm": the agent asks before every action that needs a permission, and the chat
    // shows an Allow / Deny dialog. "auto": no questions asked (--dangerously-skip-permissions).
    property string permissionMode: "confirm"
    // The mode chosen per provider, keyed by provider id: a provider without
    // the permission handshake runs unattended, but that visit must not
    // downgrade the Ask-first choice for the next one.
    property var permissionModes: ({})
    onPermissionModeChanged: syncPermissionModeMap()
    function syncPermissionModeMap() {
        if (permissionModes[providerId] === permissionMode) return;
        var map = {};
        for (var k in permissionModes) map[k] = permissionModes[k];
        map[providerId] = permissionMode;
        permissionModes = map;
        settingChosen("permissionModes", map);
        // The single key stays the current provider's mode: the settings page
        // and older configs read it.
        settingChosen("permissionMode", permissionMode);
    }
    // Which agent CLI runs the chat. "claude" is the default and keeps every setting
    // that predates the provider registry.
    property string providerId: "claude"
    // undefined when the saved id is not builtin and not in providers.json
    // (deleted while the setting survived): the UI shows that, the chat never
    // silently falls back to claude.
    readonly property var provider: { registryRevision; return Providers.byId(providerId); }
    readonly property bool providerKnown: provider !== undefined
    // Fallback descriptor for code paths that need *a* descriptor while the
    // id is unknown; every user-visible decision checks providerKnown first.
    readonly property var providerOrClaude: providerKnown ? provider : Providers.byId("claude")

    // --- External provider registry (providers.json) ---
    readonly property string registryScript: decodeURIComponent(String(Qt.resolvedUrl("registry.py")).replace(/^file:\/\//, ""))
    // The plugin's private state dir. Honours XDG_STATE_HOME so the test stand
    // (jarvis-stand runs with its own state home) never touches the real one.
    readonly property string agentStateDir: (Quickshell.env("XDG_STATE_HOME") || (homeDir + "/.local/state")) + "/dms-agent"
    readonly property string providerRegistryPath: Quickshell.env("PROVIDER_REGISTRY")
        || (agentStateDir + "/providers.json")
    // The registry is watched, not polled: registry.py replaces the file
    // atomically (rename), and a 2 s `stat` through a login shell for the
    // whole shell lifetime was a process every two seconds for nothing.
    // FileView reports writes, atomic replaces, deletion and the file
    // appearing later; reload() then produces the new text.
    FileView {
        id: providerRegistryView
        path: root.providerRegistryPath
        watchChanges: true
        onFileChanged: reload()
        onLoaded: root.loadProviderRegistry()
        // A missing file is an empty store, not a failure: the built-in
        // providers work. When it appears, fileChanged fires and the registry
        // loads on the spot.
        onLoadFailed: root.loadProviderRegistry()
    }
    // Bridge entry points for registry providers: the provider's own command
    // is the bridge's argument (AgentService.qml, _launchClaude).
    readonly property string acpBridgeScript: decodeURIComponent(String(Qt.resolvedUrl("bridges/acp_bridge.py")).replace(/^file:\/\//, ""))
    readonly property string codexBridgeScript: decodeURIComponent(String(Qt.resolvedUrl("bridges/codex_bridge.py")).replace(/^file:\/\//, ""))
    readonly property string openaiBridgeScript: decodeURIComponent(String(Qt.resolvedUrl("bridges/openai_bridge.py")).replace(/^file:\/\//, ""))
    property string bridgeScript: {
        var d = providerOrClaude;
        if (!d || !d.adapter) return "";
        if (d.adapter === "acp") return acpBridgeScript;
        if (d.adapter === "codex") return codexBridgeScript;
        if (d.adapter === "openai") {
            // The gateway bridge takes the base URL as its argument; without
            // one there is nothing to talk to.
            return d.baseUrl ? openaiBridgeScript : "";
        }
        return "";
    }
    property int registryRevision: 0
    property int _registryLoadId: 0
    function loadProviderRegistry() {
        var loadId = ++_registryLoadId;
        runQuietExit("python3 " + shellQuote(registryScript) + " list --json", function(output) {
            if (loadId !== _registryLoadId) return;
            try {
                Providers.setRegistry(JSON.parse(String(output).trim()));
                registryRevision++;
                registryReady = true;
            } catch (e) {
                // A corrupt registry keeps the builtin five working; the
                // settings UI shows the error. No silent empty-swap here.
                registryReady = false;
            }
        });
    }
    property bool registryReady: false
    // Another provider means another catalog and another set of sessions: the
    // hour-long model cache and the history both belong to the one before.
    // --- Context transfer (step 4): switching providers keeps the chat's text
    // and replays it to the new provider on its first turn. Text user/assistant
    // messages only: tool output, thinking and attachments are not carried
    // over (the plan forbids claiming a full memory transfer).
    property var _carriedContext: []
    readonly property string contextDir: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dms-agent-context"
    property string _pendingContextFile: ""
    function collectCarried() {
        var carried = [];
        for (var i = 0; i < messages.length; i++) {
            var m = messages[i];
            var c = typeof m.content === "string" ? m.content.trim() : "";
            // An "Error: …" bubble is the failed transfer itself, not part of
            // the conversation the next provider should see.
            if ((m.role === "user" || m.role === "assistant") && c !== ""
                && !m.transferError && !(m.role === "assistant" && c.indexOf("Error:") === 0))
                carried.push({ role: m.role, content: m.content });
        }
        return carried;
    }
    function carriedText(carried) {
        return carried.map(function(m) { return m.role + ": " + m.content; }).join("\n\n");
    }
    function rearmCarriedContext() {
        // Sync snapshot of the current chat: called on a provider switch, and
        // again after a failed/cancelled transfer (the plan keeps the context
        // alive for a retry, including the message that failed).
        var current = collectCarried();
        var overlap = Math.min(_carriedContext.length, current.length);
        while (overlap > 0) {
            var matches = true;
            for (var i = 0; i < overlap; i++) {
                var a = _carriedContext[_carriedContext.length - overlap + i];
                var b = current[i];
                if (a.role !== b.role || a.content !== b.content) { matches = false; break; }
            }
            if (matches) break;
            overlap--;
        }
        _carriedContext = _carriedContext.concat(current.slice(overlap));
    }
    function removeContextFile() {
        if (_pendingContextFile === "") return;
        var f = _pendingContextFile;
        _pendingContextFile = "";
        runQuietExit("rm -f " + shellQuote(f), null);
    }
    function clearChatContext() {
        _carriedContext = [];
        removeContextFile();
    }
    Component {
        id: contextWriter
        Process {
            id: writer
            property string path: ""
            property string input: ""
            property var finished: null
            command: ["python3", "-c", "import os,stat,sys\nd,p=sys.argv[1:]\nos.umask(0o077)\ntry: os.mkdir(d,0o700)\nexcept FileExistsError: pass\ns=os.lstat(d)\nif not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700: sys.exit(1)\nfd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)\nwith os.fdopen(fd,'wb') as f: f.write(sys.stdin.buffer.read())", root.contextDir, path]
            stdinEnabled: true
            onStarted: { write(input); stdinEnabled = false; }
            onExited: function(exitCode) {
                if (finished) finished(exitCode);
                destroy();
            }
        }
    }

    onProviderIdChanged: {
        // A session belongs to the provider that created it: the other CLI
        // cannot find it, and `--resume` of a missing session is a failed run
        // (blank answer, caught live 2026-11-02). A chat in flight is not carried
        // over either — it is left in the old provider's history.
        //
        // The order matters: cancelRequest() ignores a run that is still
        // loading a session, so the flag is cleared first. Otherwise the old
        // provider's process would keep running and write its answer into the
        // chat that is being cleared right here.
        loadingSession = false;
        cancelRequest();
        // Text of the conversation follows the user to the new provider as a
        // first-turn context; the native session id stays with the old one.
        var hadChat = collectCarried().length > 0;
        rearmCarriedContext();
        messages = [];
        if (hadChat) addMessage("tool_status", tr("notice.contextTransfered"));
        sessionId = "";
        lastCost = "";
        // Restore this provider's own permission mode. A provider without the
        // handshake always runs unattended (even an old map entry saying
        // otherwise); that visit must not change the Ask-first choice stored
        // for the others.
        var savedMode = permissionModes[providerId];
        permissionMode = !providerCanAskFirst ? "auto"
                        : (savedMode !== undefined ? savedMode : "confirm");
        // Restore this provider's own last model; a foreign id would be
        // rejected by --model. A first visit keeps the current one — the
        // refreshModels() fallback then picks from the new catalog. Saved here
        // too: a restore changes only these properties, and the next settings
        // reload would bring the other provider's model back.
        if (providerModels[providerId] !== undefined && providerModels[providerId] !== claudeModel) {
            claudeModel = providerModels[providerId];
            settingChosen("claudeModel", claudeModel);
        }
        _modelsFetchedAt = 0;
        refreshModels();
        loadHistory();
    }
    // Providers that cannot ask before acting (Qoder, Kimi, the bridges) always
    // run unattended; an unknown id borrows nothing from Claude Code either.
    readonly property bool providerCanAskFirst: providerKnown && providerOrClaude.caps && providerOrClaude.caps.askFirst
    // Switching to a session from the history also switches to its model and effort.
    property bool restoreSessionModel: true
    // The line under the toolbar (status, cost, session name) folded down to its toggle.
    property bool statusLineCollapsed: false
    function setStatusLineCollapsed(collapsed) {
        statusLineCollapsed = collapsed;
        settingChosen("statusLineCollapsed", collapsed);
    }
    readonly property string _noConfirmSentence: "Execute actions immediately, never ask for confirmation. "
    readonly property string _stateDirSentence: "Your working directory is a private state dir, not the user's home. "
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
        "Match fuzzy — 'brave' matches 'brave-browser-nightly', 'whatsapp' matches 'WhatsApp Web — Mozilla Firefox'.\n\n" +
        "IMPORTANT: When launching applications or running long-lived processes, ALWAYS detach them from the shell. " +
        "Use: setsid <command> >/dev/null 2>&1 & disown\n" +
        "NEVER run GUI apps in the foreground — always background and detach them.\n\n" +
        "Your working directory is a private state dir, not the user's home. " +
        "For user files always use ~ or absolute paths."

    // Set from the plugin settings (DmsAgent.qml).
    property int maxTokens: 1024
    property int bubbleFontSize: 13
    // Same limits as the slider in the settings. Changed from the chat itself
    // (Ctrl + wheel, Ctrl + / Ctrl - / Ctrl 0); DmsAgent.qml stores the result.
    readonly property int bubbleFontSizeMin: 11
    readonly property int bubbleFontSizeMax: 22
    readonly property int bubbleFontSizeDefault: 13
    signal bubbleFontSizeChosen(int size)
    // Model and effort picked in the chat's dropdowns; DmsAgent.qml stores them
    // in the same settings the settings page edits, so they survive a restart.
    signal settingChosen(string key, var value)

    function chooseModel(id) {
        // Saved before the property changes: saving reloads the settings into
        // these properties (DmsAgent.qml), which would briefly restore the old
        // model and rewrite the map from it.
        settingChosen("claudeModel", id);
        claudeModel = id;
    }

    function chooseEffort(level) {
        effort = level;
        settingChosen("effort", level);
    }

    function setBubbleFontSize(size) {
        const clamped = Math.max(bubbleFontSizeMin, Math.min(bubbleFontSizeMax, size));
        if (clamped === bubbleFontSize) return;
        bubbleFontSize = clamped;
        bubbleFontSizeChosen(clamped);
    }
    // Zoom of the whole chat window, in percent.
    property int uiScale: 100
    // Доля высоты монитора, которую занимает окно чата. Фиксированная высота
    // выглядела по-разному на широком и на вертикальном экране.
    property int panelHeightPercent: 75
    // Прозрачность фона окна чата и баблов сообщений (0–100, где 100 = непрозрачно).
    property int backgroundOpacity: 100
    // Пузыри и поле ввода как стекло: полупрозрачная подкраска, блик по кромке,
    // размытие фона под каждым пузырём (если композитор его поддерживает).
    property bool liquidGlass: false
    property string pillLabel: "Jarvis"
    property string voiceModel: "auto"
    property string voiceLanguage: "auto"
    property string voiceVenv: ""

    property bool busy: false
    property string statusText: tr("status.ready")
    property var messages: []
    property bool popoutVisible: false
    property string sessionId: ""
    property string lastCost: ""
    property var history: []
    // Name given with /rename or from the history list; empty when the session has none.
    readonly property string sessionName: {
        const h = sessionId ? history.find(x => x.id === sessionId) : null;
        return (h && h.name) ? h.name : "";
    }

    signal messageAdded(var message)
    signal responseComplete()

    // --- Voice input ---
    // pw-record writes a 16 kHz mono WAV; voice.py sends it to a local
    // faster-whisper server that keeps the model loaded between phrases.
    // Stop uses SIGTERM: on SIGINT pw-record leaves a header-only file.
    // Recording is split into 2-minute chunks; each chunk is transcribed as
    // soon as it's ready, text is appended to the input field incrementally.
    property string voiceState: "idle"    // idle | recording | transcribing
    property int voiceSeconds: 0
    property string voiceError: ""
    property bool voiceWarmupInProgress: false
    signal voiceTextReady(string text, bool isFirstChunk)

    // Chunked recording state
    property int voiceChunkDuration: 120
    property int voiceCurrentChunkSeconds: 0
    property var voiceChunkQueue: []  // [{path: string, index: int}]
    property int voiceChunkIndex: 0
    property bool voiceTranscribing: false
    property bool voiceSessionStarted: false

    // What the current recording listens to:
    //   "mic"    — the microphone (a named one from the settings, else the system default)
    //   "output" — whatever is playing on the speakers or headphones, for transcribing
    //              the other side of a call when your mic cannot hear them
    property string voiceSource: "mic"
    // Empty means "whatever the system picked"; otherwise a PipeWire source name.
    property string voiceDevice: ""
    // Loads the speech model when the chat opens, so the first dictation is not clipped.
    property bool voiceWarmup: false

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
            property string wavPath: ""
            // "stream.capture.sink=true" attaches the stream to the monitor of the
            // *current* output, so it follows a switch from speakers to headphones
            // on its own — no need to look the device up.
            command: {
                var cmd = ["pw-record"];
                if (root.voiceSource === "output") cmd.push("-P", "stream.capture.sink=true");
                else if (root.voiceDevice !== "") cmd.push("--target", root.voiceDevice);
                return cmd.concat(["--rate", "16000", "--channels", "1", "--format", "s16", wavPath]);
            }
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
            root.voiceCurrentChunkSeconds += 1;
            if (root.voiceCurrentChunkSeconds >= root.voiceChunkDuration) {
                root._rotateChunk();
            }
        }
    }

    function startVoice(source) {
        // During a run only a provider that reads stdin could take the text
        // while it works; the rest wait for the next message (the mic button is
        // hidden for them). The recognition itself lands in the input field,
        // and Send is Stop until the run ends.
        if ((busy && !(providerOrClaude.caps && providerOrClaude.caps.stdinEnabled)) || voiceState !== "idle") return;
        voiceSource = source === "output" ? "output" : "mic";
        voiceError = "";
        voiceSeconds = 0;
        voiceCurrentChunkSeconds = 0;
        voiceChunkIndex = 0;
        voiceChunkQueue = [];
        voiceSessionStarted = true;
        _recCancelled = false;
        _startChunk();
        voiceState = "recording";
    }

    function _startChunk() {
        var chunkPath = voiceWav + "-" + voiceChunkIndex;
        var p = recRunner.createObject(root, { wavPath: chunkPath });
        _recProcess = p;
        p.running = true;
    }

    function _rotateChunk() {
        if (!_recProcess) return;
        var currentPath = voiceWav + "-" + voiceChunkIndex;
        
        // Завершаем текущий процесс записи
        _recProcess.signal(15);
        
        // Добавляем в очередь транскрибации
        voiceChunkQueue = voiceChunkQueue.concat([{path: currentPath, index: voiceChunkIndex}]);
        
        // Запускаем обработку очереди, если она не идёт
        if (!voiceTranscribing) _processNextChunk();
        
        // Следующий чанк
        voiceChunkIndex += 1;
        voiceCurrentChunkSeconds = 0;
        _startChunk();
    }

    function stopVoice() {
        if (voiceState !== "recording" || !_recProcess) return;
        
        // Финализируем последний чанк
        var currentPath = voiceWav + "-" + voiceChunkIndex;
        voiceChunkQueue = voiceChunkQueue.concat([{path: currentPath, index: voiceChunkIndex}]);
        
        _recProcess.signal(15);
        voiceState = "transcribing";
        
        // Запускаем обработку очереди
        if (!voiceTranscribing) _processNextChunk();
    }

    function cancelVoice() {
        if (voiceState !== "recording" || !_recProcess) return;
        _recCancelled = true;
        _recProcess.signal(15);
    }

    function warmupVoice() {
        // Прогрев Whisper-модели и PipeWire для первой записи:
        // записываем 1 секунду тишины, отправляем на транскрибацию, игнорируем результат.
        voiceWarmupInProgress = true;
        
        var warmupPath = (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dms-agent-warmup.wav";
        
        var cmd = ["pw-record"];
        if (voiceSource === "output") cmd.push("-P", "stream.capture.sink=true");
        else if (voiceDevice !== "") cmd.push("--target", voiceDevice);
        cmd = cmd.concat(["--rate", "16000", "--channels", "1", "--format", "s16", warmupPath]);
        
        var env = "DMS_AGENT_WHISPER_MODEL=" + shellQuote(voiceModel)
            + " DMS_AGENT_WHISPER_LANG=" + shellQuote(voiceLanguage)
            + " DMS_AGENT_WHISPER_VENV=" + shellQuote(voiceVenv)
            + " DMS_AGENT_WHISPER_IDLE=7200 ";
        
        // Записываем 1 секунду, затем транскрибируем и удаляем
        runQuietExit("timeout 1s " + cmd.map(shellQuote).join(" ") + " 2>/dev/null; "
            + env + "python3 " + shellQuote(voiceScript) + " transcribe " + shellQuote(warmupPath) + " >/dev/null 2>&1; "
            + "rm -f " + shellQuote(warmupPath), function() {
            voiceWarmupInProgress = false;
        });
    }

    function stopWhisperServer() {
        // Останавливаем Whisper-сервер при закрытии окна чата для освобождения памяти (~900 МБ).
        // Сервер поднимается заново при следующей диктовке или прогреве (voiceWarmup).
        runQuietExit("python3 " + shellQuote(voiceScript) + " stop", function() {});
    }

    function _onRecordingExited() {
        var wasRotation = voiceState === "recording";
        _recProcess = null;
        
        if (_recCancelled) {
            // Отменено пользователем — удаляем все чанки и очищаем очередь
            voiceState = "idle";
            for (var i = 0; i < voiceChunkQueue.length; i++) {
                runQuietExit("rm -f " + shellQuote(voiceChunkQueue[i].path), function() {});
            }
            voiceChunkQueue = [];
            return;
        }
        
        if (wasRotation) {
            // Ротация чанка — процесс уже запущен в _rotateChunk()
            return;
        }
        
        // Если процесс умер сам (нет микрофона, PipeWire упал)
        if (voiceState === "recording") {
            voiceError = tr(voiceSource === "output" ? "error.noOutput" : "error.micUnavailable");
            voiceState = "idle";
            for (var j = 0; j < voiceChunkQueue.length; j++) {
                runQuietExit("rm -f " + shellQuote(voiceChunkQueue[j].path), function() {});
            }
            voiceChunkQueue = [];
            return;
        }
    }

    function _processNextChunk() {
        if (voiceChunkQueue.length === 0) {
            voiceTranscribing = false;
            if (voiceState === "transcribing") {
                // Все чанки обработаны, сессия завершена
                voiceState = "idle";
                voiceSessionStarted = false;
            }
            return;
        }
        
        voiceTranscribing = true;
        var chunk = voiceChunkQueue[0];
        voiceChunkQueue = voiceChunkQueue.slice(1);
        
        var isFirstChunk = voiceSessionStarted;
        if (isFirstChunk) voiceSessionStarted = false;
        
        var env = "DMS_AGENT_WHISPER_MODEL=" + shellQuote(voiceModel)
            + " DMS_AGENT_WHISPER_LANG=" + shellQuote(voiceLanguage)
            + " DMS_AGENT_WHISPER_VENV=" + shellQuote(voiceVenv)
            + " DMS_AGENT_WHISPER_IDLE=7200 ";
        runQuietExit(env + "python3 " + shellQuote(voiceScript) + " transcribe " + shellQuote(chunk.path)
                + "; rm -f " + shellQuote(chunk.path), function(output) {
            var result = {};
            try { result = JSON.parse(String(output).trim()); } catch(e) {}
            
            if (result.text) {
                // Вызываем сигнал с флагом первого чанка
                voiceTextReady(result.text, isFirstChunk);
            }
            
            // Следующий чанк
            _processNextChunk();
        });
    }

    // --- Attachments for the next message ---
    // The agent reads files with its own reading tool, so an attachment is just
    // a path handed to it in the prompt. Each entry is {path, kind}: "shot" for
    // screenshots this plugin took, "file" for something the user picked.
    // The difference matters on removal — a screenshot is ours to delete, a
    // chosen file is not.
    property var pendingAttachments: []
    property string attachError: ""

    readonly property string screenshotScript: decodeURIComponent(String(Qt.resolvedUrl("screenshot.sh")).replace(/^file:\/\//, ""))
    readonly property string pickScript: decodeURIComponent(String(Qt.resolvedUrl("pickfiles.py")).replace(/^file:\/\//, ""))
    readonly property string openScript: decodeURIComponent(String(Qt.resolvedUrl("openfile.py")).replace(/^file:\/\//, ""))
    readonly property string screenshotDir: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp")

    function captureWindow() {
        var path = screenshotDir + "/dms-agent-shot-" + Date.now() + ".png";
        attachError = "";
        run(shellQuote(screenshotScript) + " " + shellQuote(path) + " 2>&1", function(output) {
            if (String(output).trim() !== "ok") {
                // The chat holds keyboard focus but not window focus, so this only
                // happens when there is genuinely no window to shoot.
                attachError = tr("error.noWindow");
                return;
            }
            pendingAttachments = pendingAttachments.concat([{ path: path, kind: "shot" }]);
        });
    }

    function pickFiles() {
        attachError = "";
        run("python3 " + shellQuote(pickScript), function(output) {
            var lines = String(output).split("\n");
            var added = [];
            for (var i = 0; i < lines.length; i++) {
                var path = lines[i].trim();
                if (path !== "") added.push({ path: path, kind: "file" });
            }
            if (added.length > 0) pendingAttachments = pendingAttachments.concat(added);
        });
    }

    function removeAttachment(path) {
        var kept = [];
        var wasShot = false;
        for (var i = 0; i < pendingAttachments.length; i++) {
            var item = pendingAttachments[i];
            if (item.path === path) wasShot = item.kind === "shot";
            else kept.push(item);
        }
        pendingAttachments = kept;
        // Only screenshots are ours: deleting a file the user chose would be
        // deleting their document.
        if (wasShot) runQuietExit("rm -f " + shellQuote(path), function() {});
    }

    function clearAttachments(keepFiles) {
        if (!keepFiles) {
            for (var i = 0; i < pendingAttachments.length; i++) {
                if (pendingAttachments[i].kind === "shot")
                    runQuietExit("rm -f " + shellQuote(pendingAttachments[i].path), function() {});
            }
        }
        pendingAttachments = [];
    }

    function openAttachment(path) {
        // Opens with whatever the desktop registered for that file's type, and
        // offers the "open with" chooser when the type has no handler.
        runQuietExit("python3 " + shellQuote(openScript) + " " + shellQuote(path), function() {});
    }

    // --- Update notice ---
    // Only tells that a newer version exists; installing it is up to DMS
    // (Settings → Plugins → Update). Checked once per boot: the marker lives in
    // the runtime dir, which is wiped on reboot but survives a shell restart.
    property bool updateNotify: false

    readonly property string updateScript: decodeURIComponent(String(Qt.resolvedUrl("check-update.sh")).replace(/^file:\/\//, ""))
    readonly property string updateMarker: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/dms-agent-update-checked"

    function checkForUpdates() {
        if (!updateNotify) return;

        // The marker is created before the work, so a failure does not retry on
        // every shell restart for the rest of the session.
        runQuietExit("test -e " + shellQuote(updateMarker) + " && echo skip || touch " + shellQuote(updateMarker), function(output) {
            if (String(output).trim() === "skip") return;
            run(shellQuote(updateScript), function(result) {
                if (String(result).trim() !== "available") return;
                runQuietExit("dms notify --app " + shellQuote(pillLabel) + " "
                    + shellQuote(tr("update.available")) + " " + shellQuote(tr("update.how")), function() {});
            });
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
                runQuietExit("dms notify --app 'DMS AI Agent' 'Hotkey not applied' " + shellQuote(text.substring(0, 200)), function() {});
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

    // Where the chat sits on each monitor, keyed by screen name: a preset
    // ("left" | "center" | "right") or, after Ctrl + drag, a number from 0 (left
    // edge) to 1 (right edge) — the share of the free width left of the chat. The
    // monitors differ enough (one wide, one portrait) that a single shared setting
    // would suit neither.
    property var panelPositions: ({})
    property bool positionsLoaded: false

    signal panelPositionChanged(string screenName, string position)

    // The preset name, or "custom" for a dragged position (no button is lit).
    function panelPositionFor(screenName) {
        var v = panelPositions[screenName];
        if (v === undefined || v === null) return "center";
        return typeof v === "number" ? "custom" : v;
    }

    function panelFractionFor(screenName) {
        var v = panelPositions[screenName];
        if (typeof v === "number") return Math.max(0, Math.min(1, v));
        return v === "left" ? 0 : (v === "right" ? 1 : 0.5);
    }

    // A drop close to a preset snaps to it, so its button lights up again.
    function setPanelFraction(screenName, fraction) {
        var f = Math.max(0, Math.min(1, fraction));
        var presets = { left: 0, center: 0.5, right: 1 };
        for (var name in presets)
            if (Math.abs(f - presets[name]) < 0.015) { setPanelPosition(screenName, name); return; }
        setPanelPosition(screenName, Math.round(f * 10000) / 10000);
    }

    function setPanelPosition(screenName, position) {
        if (panelPositions[screenName] === position || (panelPositions[screenName] === undefined && position === "center")) return;
        var next = {};
        for (var key in panelPositions) next[key] = panelPositions[key];
        next[screenName] = position;
        panelPositions = next;   // a fresh object, so bindings on it re-evaluate
        panelPositionChanged(screenName, position);
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
    // too, so both are launched from here. The setting can point the agent at
    // any other directory, e.g. a project: the chats and their history then
    // belong to that directory, as with `claude` started there.
    property string customWorkDir: ""
    // Directories picked in the chat popup, newest first, kept in the plugin settings.
    property var recentWorkDirs: []
    readonly property int recentWorkDirsMax: 8
    readonly property string defaultWorkDir: homeDir + "/.local/state/dms-agent"
    readonly property string workDir: customWorkDir !== "" ? customWorkDir : defaultWorkDir
    readonly property string cdWorkDir: (customWorkDir !== "" ? "" : "mkdir -p " + shellQuote(workDir) + " && ")
        + "cd " + shellQuote(workDir) + " && "

    // "~", "~/x" and plain relative paths (taken from $HOME) become absolute.
    function normalizeDir(path) {
        var p = String(path || "").trim();
        if (p === "") return "";
        if (p === "~" || p.indexOf("~/") === 0) p = homeDir + p.substring(1);
        else if (p.charAt(0) !== "/") p = homeDir + "/" + p;
        while (p.length > 1 && p.charAt(p.length - 1) === "/") p = p.substring(0, p.length - 1);
        return p;
    }

    // The chat's directory popup. Goes through the plugin settings, so the settings
    // page and the chat always show the same value; DmsAgent.qml applies it.
    function chooseWorkDir(path, done) {
        var dir = normalizeDir(path);
        if (dir === defaultWorkDir) dir = "";
        if (dir === "") { settingChosen("workDir", ""); done(true); return; }
        runQuietExit("test -d " + shellQuote(dir) + " && echo ok || echo missing", function(output) {
            var ok = String(output).trim() === "ok";
            if (ok) {
                settingChosen("workDir", dir);
                rememberWorkDir(dir);
            }
            done(ok);
        });
    }

    function rememberWorkDir(dir) {
        var list = [dir].concat(recentWorkDirs.filter(function(d) { return d !== dir; }));
        settingChosen("recentWorkDirs", list.slice(0, recentWorkDirsMax));
    }

    function forgetWorkDir(dir) {
        settingChosen("recentWorkDirs", recentWorkDirs.filter(function(d) { return d !== dir; }));
    }

    // Folder chooser of the desktop (the same portal dialog as for attachments).
    function pickWorkDir(done) {
        run("python3 " + shellQuote(pickScript) + " --dir " + shellQuote(workDir), function(output) {
            var path = String(output).split("\n")[0].trim();
            if (path !== "") done(path);
        });
    }

    // A conversation cannot move between directories (Claude Code keeps them per
    // project), so changing the directory starts with a clean chat and that
    // directory's own history.
    function setWorkDir(path) {
        var dir = normalizeDir(path);
        if (dir === defaultWorkDir) dir = "";
        if (dir === customWorkDir) return;
        // Empty the conversation first: the chat reloads its feed on the directory change.
        clearMessages();
        customWorkDir = dir;
        loadHistory();
    }

    Component.onCompleted: {
        // Orphaned transfer files from a crashed previous instance: the runtime
        // dir holds nothing but this plugin's context files, and no live
        // instance can exist when this one starts — wipe it, not just the
        // files older than some age. The plan requires cleanup "at the next
        // start after a crash".
        runQuietExit("rm -rf " + shellQuote(contextDir), null);
        // The registry's initial load comes from its FileView (onLoaded).
        loadHistory(); refreshModels();
    }

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
        if (loadingSession) { loadingSession = false; busy = false; }
        else if (busy) {
            cancelRequest();
            if (_claudeProcess) { _claudeProcess.signal(15); _claudeProcess = null; }
        }
        _requestId++;
        clearChatContext();
        messages = [];
        sessionId = "";
        lastCost = "";
    }

    // --- Notification ---
    function notifyIfHidden(text) {
        if (popoutVisible) return;
        runQuietExit("dms notify --app " + shellQuote(pillLabel) + " --icon smart_toy 'Agent' " + shellQuote(String(text).substring(0, 100)), function() {});
    }

    // --- History (reads from Claude CLI session files) ---
    // Resolved next to this file: the plugin directory name depends on how it was installed.
    readonly property string historyScript: decodeURIComponent(String(Qt.resolvedUrl("history.py")).replace(/^file:\/\//, ""))

    function loadHistory() {
        // Each row includes its working directory; foreign sessions are
        // restored as text because native resume is scoped to this directory.
        runQuietExit(cdWorkDir + "python3 " + shellQuote(historyScript) + " --provider " + shellQuote(providerId) + " list --all-dirs", function(output) {
            try { history = JSON.parse(String(output).trim()); } catch(e) { history = []; }
        });
    }

    // Deleting a session removes its transcript from disk — there is no other
    // copy. Confirmation happens in the UI before either of these is called.
    function deleteSession(historySessionId) {
        runQuietExit(cdWorkDir + "python3 " + shellQuote(historyScript) + " --provider " + shellQuote(providerId) + " delete " + shellQuote(historySessionId), function(output) {
            var removed = false;
            try { removed = JSON.parse(String(output).trim()).removed === 1; } catch(e) {}
            if (!removed) {
                // "deleted: 0" alone was invisible: the row stayed and nothing
                // said why. The reason is the panel not offering it again.
                statusText = tr("error.deleteFailed");
                notifyIfHidden(statusText);
            }
            // Wiping the session being displayed leaves the chat pointing at a
            // transcript that no longer exists, so it is reset to a fresh one.
            if (sessionId === historySessionId && removed) clearMessages();
            loadHistory();
        });
    }

    function renameSession(historySessionId, title) {
        runQuietExit(cdWorkDir + "python3 " + shellQuote(historyScript) + " --provider " + shellQuote(providerId) + " rename " + shellQuote(historySessionId) + " " + shellQuote(title), function() {
            loadHistory();
        });
    }

    function deleteAllSessions() {
        runQuietExit(cdWorkDir + "python3 " + shellQuote(historyScript) + " --provider " + shellQuote(providerId) + " delete-all", function(output) {
            var failed = 0;
            try { failed = JSON.parse(String(output).trim()).failed || 0; } catch(e) {}
            if (failed > 0) {
                statusText = tr("error.deleteFailed");
                notifyIfHidden(statusText);
            }
            clearMessages();
            loadHistory();
        });
    }

    // Picks the model and effort a session was left with, as recorded in its transcript
    // (the resolved model id, e.g. "claude-sonnet-5-5"). The picker lists aliases, so the
    // id is matched against them first.
    function applySessionModel(model, level) {
        if (!model) return;
        // No match (the list not fetched yet, or a model it no longer offers): leave the
        // choice alone rather than pin the default to a full versioned id.
        const m = models.find(x => x.resolved === model) || models.find(x => x.id === model);
        if (!m) return;
        if (m.id !== claudeModel) chooseModel(m.id);
        if (level && level !== effort && effortLevels.indexOf(level) >= 0) chooseEffort(level);
    }

    // Loading a session is not a request to the agent: Stop has nothing to end
    // while it runs, so the button is shown dimmed.
    property bool loadingSession: false

    function resumeSession(historySessionId, historyWorkDir) {
        if (busy) return false;
        clearChatContext();
        var request = ++_requestId;
        var restoreDir = workDir;
        sessionId = historySessionId;
        messages = [];
        busy = true;
        loadingSession = true;
        statusText = tr("status.loadingSession");

        // The restore reads the transcripts of the provider that is current
        // now. A provider switch while it runs makes the answer belong to the
        // other CLI — it must not land in the chat that was just cleared.
        var restoreProvider = providerId;

        runQuietExit(cdWorkDir + "python3 " + shellQuote(historyScript) + " --provider " + shellQuote(providerId) + " restore " + shellQuote(historySessionId) + " " + shellQuote(historyWorkDir || ""), function(output) {
            if (request !== _requestId || restoreProvider !== providerId || restoreDir !== workDir) return;
            var loaded = [];
            var restored = {};
            try { restored = JSON.parse(String(output).trim()); } catch(e) {}
            if (Array.isArray(restored)) loaded = restored;
            else if (restored && Array.isArray(restored.messages)) loaded = restored.messages;
            // A transcript can live in another directory (the panel lists
            // --all-dirs). Its text is read fine, but a native --resume from
            // here would not find that session — so the id is not kept, and
            // the conversation becomes a context transfer instead: the next
            // message replays it to the provider as text.
            var originDir = restored && !Array.isArray(restored) ? String(restored.originDir || "") : "";
            var foreignDir = originDir !== "" && originDir !== workDir;
            if (foreignDir) sessionId = "";
            if (restoreSessionModel && restored && !Array.isArray(restored)
                && providerOrClaude.caps && providerOrClaude.caps.perSessionRestore)
                applySessionModel(restored.model, restored.effort);
            for (var i = 0; i < loaded.length; i++) {
                loaded[i].timestamp = Date.now();
                var newMsgs = messages.slice();
                newMsgs.push(loaded[i]);
                messages = newMsgs;
                messageAdded(loaded[i]);
            }
            if (loaded.length === 0) {
                // The transcript is gone or unreadable. For a provider whose
                // history is its own transcripts, resuming this id would fail
                // on every later message; start a fresh session instead. A
                // registry-backed provider keeps the id: its native resume may
                // still work without a readable transcript.
                if (!(providerOrClaude.caps && providerOrClaude.caps.registryHistory)) sessionId = "";
                addMessage("assistant", "Session resumed.");
            } else if (foreignDir) {
                addMessage("tool_status", tr("notice.foreignDirResumed"));
            }
            // The restored text must ride along: arm the transfer (openai
            // replays it every turn; a provider switch carries it too).
            if (foreignDir) rearmCarriedContext();
            loadingSession = false;
            busy = false;
            statusText = tr("status.ready");
        });
        return true;
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
        var request = ++_requestId;

        var intent = detectIntent(text);
        if (intent) {
            prefetchContext(intent, function(ctx) { if (request === _requestId) callClaude(text + "\n" + ctx); });
        } else {
            statusText = tr("status.thinking");
            callClaude(text);
        }
    }

    // --- Pre-fetch context ---
    function prefetchContext(intent, callback) {
        if (intent.intent === "goto") {
            statusText = tr("status.scanningWindows");
            runQuietExit("niri msg -j windows 2>/dev/null", function(output) {
                var windows; try { windows = JSON.parse(output); } catch(e) { windows = []; }
                var summary = windows.map(function(w) {
                    return "id:" + w.id + " app:" + w.app_id + " title:\"" + w.title + "\"" + (w.is_focused ? " (focused)" : "");
                }).join("\n");
                callback("[Open windows]\n" + summary);
            });
        } else if (intent.intent === "close") {
            statusText = tr("status.scanningProcesses");
            runQuietExit("ps aux | grep -iv grep | grep -i " + shellQuote(intent.target) + " | head -10", function(output) {
                callback("[Matching processes]\n" + String(output).trim());
            });
        } else if (intent.intent === "open") {
            statusText = tr("status.searchingApps");
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
    // Tool calls the agent is waiting on in confirm mode, oldest first (it may ask for several
    // at once): { requestId, input, text }. The first one is shown; the rest wait their turn.
    property var permissionQueue: []
    readonly property var pendingPermission: permissionQueue.length > 0 ? permissionQueue[0] : null

    function _sendControl(proc, requestId, subtype, response) {
        var body = subtype === "success" ? { subtype: "success", request_id: requestId, response: response }
                                         : { subtype: "error", request_id: requestId, error: response };
        proc.write(JSON.stringify({ type: "control_response", response: body }) + "\n");
    }

    function respondPermission(allow) {
        var p = pendingPermission, proc = _claudeProcess;
        if (!p) return;
        permissionQueue = permissionQueue.slice(1);
        if (!proc) return;
        if (permissionQueue.length === 0)
            statusText = tr(activeEffort !== "" ? "status.thinking" : "status.processing");
        _sendControl(proc, p.requestId, "success", allow ? { behavior: "allow", updatedInput: p.input }
                                                         : { behavior: "deny", message: "The user denied this action." });
    }

    // What the dialog shows: everything that will run, not the one-line summary of the chat.
    function permissionText(name, input) {
        var inp = (input && typeof input === "object") ? input : {};
        var body = inp.command || inp.content || inp.new_string || "";
        var label = name || "tool";
        var head = label + (inp.file_path ? ": " + inp.file_path : "");
        var hasArgs = Object.keys(inp).length > 0;
        // An ACP permission request carries a tool title and often no
        // arguments: "undefined\n{}" is not a question anyone can answer.
        var text = body ? head + "\n" + body
                        : (inp.file_path ? head
                                         : (hasArgs ? label + "\n" + JSON.stringify(inp, null, 1) : label));
        if (homeDir) text = text.split(homeDir).join("~");
        return text.length > 4000 ? text.substring(0, 4000) + "\n…" : text;
    }

    Component {
        id: claudeRunner
        Process {
            id: claudeProc
            property string shellCmd: ""
            // Confirm mode talks to the agent over stdin (the answers to its permission requests).
            property string input: ""
            stdinEnabled: input !== ""
            command: ["bash", "-lc", shellCmd]
            onStarted: if (input !== "") write(input)
            stdout: SplitParser {
                onRead: data => {
                    if (root._claudeProcess === claudeProc && !root._cancelled) root.handleStreamLine(data);
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
                root._runningProvider = null;
                root.permissionQueue = [];
                root.removeContextFile();
                if (root._carriedContext.length > 0) root.rearmCarriedContext();
                if (root._cancelled) {
                    var sameProvider = root._cancelProvider === root.providerId;
                    root._cancelled = false;
                    root._cancelProvider = "";
                    root.lastCost = "";
                    if (sameProvider) root.finishResponse(root.tr("status.cancelled"));
                } else {
                    root.finishResponse(root._lastText || "(error: agent exited without a response)");
                }
            }
        }
    }

    // Bumped by every message and by Stop. The steps before claude starts (context
    // prefetch, the working directory check) run asynchronously; one that finds
    // the number changed was stopped meanwhile and must not launch the agent.
    property int _requestId: 0
    // Set when the user pressed Stop: the run that ends after that is a
    // cancellation, not a failure, and its error text is not shown.
    property bool _cancelled: false
    // The provider descriptor of the RUNNING process. A switch changes
    // providerId first, so the descriptor looked up by id at that moment is the
    // new one: Cancel would speak the wrong protocol to the old CLI and the
    // cancellation marker would name the new provider, letting "Cancelled"
    // appear in the chat that was just cleared.
    property var _runningProvider: null
    // The provider the cancelled run belonged to. A provider switch cancels
    // the old run too, but its answer belongs to the chat that was just
    // cleared — it must not appear in the new provider's chat.
    property string _cancelProvider: ""

    function cancelRequest() {
        if (loadingSession) return;
        permissionQueue = [];
        exitGrace.stop();
        cancelFallback.stop();
        cancelCloseStdin.stop();
        _requestId++;
        removeContextFile();
        if (_carriedContext.length > 0) rearmCarriedContext();
        _cancelled = true;
        // The descriptor (and the protocol) of the run that is actually
        // running, not of whatever provider the settings now point at.
        var running = _runningProvider || providerOrClaude;
        _cancelProvider = _runningProvider ? _runningProvider.id : providerId;
        if (_claudeProcess) {
            var proc = _claudeProcess;
            // The claude CLI stops the current turn on a control_request/interrupt
            // and answers with a result event; SIGTERM does not — the run
            // would end with no result at all, and the chat would show
            // "agent exited without a response" instead of "Cancelled".
            // The signal stays as a fallback for a CLI that ignores the
            // interrupt, sent only after the CLI had time to answer. A bridge
            // provider reads its own {"type":"cancel"} line instead.
            if (running.caps && running.caps.cancelViaStdin) {
                try {
                    proc.write(JSON.stringify(Providers.cancelMessage(running, _requestId)) + "\n");
                    cancelCloseStdin.restart();
                    cancelFallback.restart();
                } catch (e) {
                    // Could not write (the pipe is already gone): stop it the
                    // hard way and let exitGrace report the cancellation.
                    proc.signal(15);
                }
            } else {
                // No stdin protocol to interrupt: the signal is the only stop.
                // _claudeProcess stays set so its exit reaches exitGrace and the
                // chat gets the same "Cancelled" answer as the stdin providers;
                // late stdout lines are dropped by the !_cancelled guard.
                proc.signal(15);
            }
        }
        if (busy) {
            busy = false;
            statusText = tr("status.ready");
        }
    }

    // The CLI had its chance to answer the interrupt; if it is still running,
    // it is stopped for good.
    Timer {
        id: cancelFallback
        interval: 3000
        onTriggered: {
            if (root._claudeProcess) {
                root._claudeProcess.signal(15);
                root._claudeProcess = null;
            }
            root._runningProvider = null;
        }
    }

    // An interrupted run ends when its stdin closes; the CLI keeps the pipe
    // open otherwise and the process would stay alive until the fallback
    // signal.
    Timer {
        id: cancelCloseStdin
        interval: 1500
        onTriggered: {
            if (root._claudeProcess)
                root._claudeProcess.stdinEnabled = false;
        }
    }

    function callClaude(prompt) {
        if (customWorkDir === "") { _launchClaudeChecked(prompt); return; }
        var request = _requestId;
        // A typo in the setting should say so, not end in "agent exited".
        runQuietExit("test -d " + shellQuote(customWorkDir) + " && echo ok || echo missing", function(output) {
            if (request !== _requestId) return;
            if (String(output).trim() === "ok") _launchClaudeChecked(prompt);
            else finishResponse(tr("error.workDirMissing") + " " + customWorkDir);
        });
    }

    // Every provider is checked before its CLI is launched: a run without a
    // login can only fail with auth noise, so the chat says "not signed in" and
    // the command that fixes it instead. A success is remembered (the check is
    // a process per provider), a failure is re-checked on the next send — after
    // the user logs in, the very next message goes through.
    property var _signedIn: ({})
    function _launchClaudeChecked(prompt) {
        // The saved id has no descriptor (removed from providers.json, or the
        // registry file is corrupt): say so, never launch a different CLI.
        if (!providerKnown) {
            finishResponse(tr("error.unknownProvider") + " " + providerId);
            return;
        }
        // The model id is resolved through the catalog. Right after a provider
        // switch the list still belongs to the previous provider, and a CLI
        // handed another provider's id ("Qwen3.8-Flash" to claude) fails with
        // no explanation. Claude keeps working: its bare aliases are valid
        // without the catalog.
        if (!providerOrClaude.aliasModels && _modelsProvider !== providerId) {
            refreshModels();
            finishResponse(tr("error.modelsNotReady"));
            return;
        }
        if (!providerOrClaude.aliasModels && modelsError !== "") {
            finishResponse(modelsError);
            return;
        }
        if (_signedIn[providerId] === true && !providerOrClaude.liveSignIn) { _launchChecked(prompt); return; }
        var request = _requestId;
        runQuietExit("python3 " + shellQuote(secretsScript) + " check " + shellQuote(providerId), function(output) {
            if (request !== _requestId) return;
            if (String(output).trim() === "set") {
                // A live service check is not a login: caching it would keep
                // the answer "signed in" for the rest of the shell's life.
                if (!providerOrClaude.liveSignIn) _signedIn[providerId] = true;
                _launchChecked(prompt);
            } else {
                // A registry provider names its adapter (codex, an OpenAI
                // gateway) or falls back to the generic line instead of
                // showing the key name itself.
                var hintKey = Providers.hintKey(providerOrClaude);
                var hint = I18n.has(uiLanguage, hintKey) ? tr(hintKey) : tr("loginHint.generic");
                finishResponse(tr("error.notLoggedIn") + " (" + provider.title + "). " + hint);
            }
        });
    }

    function _launchClaude(prompt) {
        // Context transfer (step 4): a carried chat goes along as a context
        // file for the registry bridges (written 0600 before the launch), and
        // as text prepended to the prompt for every CLI that takes the query
        // as an argument or on stdin — claude, CVC, Qoder and Kimi alike.
        var carried = _carriedContext;
        if (carried.length > 0 && providerOrClaude.bridge) {
            statusText = tr("status.processing");
            var request = _requestId;
            var path = contextDir + "/ctx-" + Date.now() + "-" + request + "-" + Math.random().toString(36).slice(2) + ".jsonl";
            var writer = contextWriter.createObject(root, {
                path: path,
                input: carried.map(function(m) { return JSON.stringify(m); }).join("\n") + "\n",
                finished: function(exitCode) {
                    if (request !== _requestId || exitCode !== 0) {
                        runQuietExit("rm -f " + shellQuote(path), null);
                        if (request === _requestId) {
                            rearmCarriedContext();
                            finishResponse(tr("error.contextUnsupported"), true);
                        }
                        return;
                    }
                    _pendingContextFile = path;
                    _launchNow(prompt);
                }
            });
            writer.running = true;
            return;
        }
        _launchNow(carried.length > 0 ? carriedText(carried) + "\n\n" + prompt : prompt);
    }

    function _launchChecked(prompt) {
        // openai keeps no server-side session: replay the full chat each turn.
        if (providerOrClaude.adapter === "openai" && sessionId === "" && _carriedContext.length === 0) {
            var chat = collectCarried();
            _carriedContext = chat.slice(0, Math.max(0, chat.length - 1));
        }
        _launchClaude(prompt);
    }

    function _launchNow(prompt) {
        exitGrace.stop();
        cancelFallback.stop();
        cancelCloseStdin.stop();
        // A run the user stopped can still be alive: the CLI answers the
        // interrupt with a result event and then waits on stdin. If a new
        // message starts before that (Stop clears busy at once, so it can),
        // close the old pipe now — otherwise its timers are cancelled below,
        // its exit is ignored (it is no longer _claudeProcess) and the process
        // lingers forever. The new run owns the timers from here.
        if (_claudeProcess) {
            try { _claudeProcess.stdinEnabled = false; } catch (e) {}
            _claudeProcess = null;
        }
        _runningProvider = null;
        statusText = tr(activeEffort !== "" ? "status.thinking" : "status.processing");
        _gotResult = false;
        _cancelled = false;
        _cancelProvider = "";
        _lastText = "";
        _toolNames = ({});

        // exec: bash is replaced by the agent CLI, so Cancel's SIGTERM reaches the agent itself.
        var confirm = providerCanAskFirst && permissionMode !== "auto";
        var prompt_ = confirm ? systemPrompt.replace(_noConfirmSentence, "") : systemPrompt;
        if (customWorkDir !== "")
            prompt_ = prompt_.replace(_stateDirSentence, "Your working directory is " + customWorkDir + ", a directory the user chose: relative paths refer to it. ");
        var cmd = cdWorkDir + providerOrClaude.buildCommand({
            model: cliModel,
            effort: activeEffort,
            confirm: confirm,
            systemPrompt: prompt_,
            prompt: prompt,
            resumeId: sessionId,
            secretsScript: secretsScript,
            stateDir: agentStateDir,
            bridgeScript: bridgeScript,
            q: shellQuote
        });
        _runningProvider = providerOrClaude;

        var props = { shellCmd: cmd };
        // The prompt goes in through stdin for every provider whose CLI speaks
        // stream-json input: the same pipe is what Cancel writes the
        // interrupt into. A provider with no stdin format (Qoder, Kimi) takes
        // the prompt as an argument and can only be stopped by a signal.
        if (providerOrClaude.stdinUserFormat) {
            var input = "";
            // Registry bridges take a config line (model/effort/resumeId)
            // before the user message; the claude CLI gets these as flags.
            if (providerOrClaude.bridge) {
                var cfg = { type: "config" };
                if (cliModel) cfg.model = cliModel;
                if (activeEffort) cfg.effort = activeEffort;
                if (sessionId) cfg.resumeId = sessionId;
                if (prompt_) cfg.systemPrompt = prompt_;
                // Context transfer (step 4): the file is sent only on the
                // first turn after a provider switch, then dropped — later
                // turns go through the new provider's native history.
                if (_pendingContextFile !== "") {
                    cfg.contextFile = _pendingContextFile;
                }
                input += JSON.stringify(cfg) + "\n";
            }
            input += JSON.stringify(providerOrClaude.stdinUserFormat(prompt)) + "\n";
            props.input = input;
        }
        var p = claudeRunner.createObject(root, props);
        _claudeProcess = p;
        p.running = true;
    }

    function handleStreamLine(line) {
        var events = providerOrClaude.parseLine(line);
        for (var i = 0; i < events.length; i++) handleStreamEvent(events[i]);
    }

    function handleStreamEvent(ev) {
        var content = ev.message && Array.isArray(ev.message.content) ? ev.message.content : [];

        if (ev.type === "control_request") {
            var req = ev.request || {};
            if (req.subtype === "can_use_tool") {
                var queue = permissionQueue.slice();
                queue.push({ requestId: ev.request_id, input: req.input || {},
                             text: permissionText(req.tool_name, req.input) });
                permissionQueue = queue;
                statusText = tr("status.awaiting");
                notifyIfHidden(tr("permission.notify") + ": " + describeTool(req.tool_name, req.input));
            } else if (_claudeProcess) {
                _sendControl(_claudeProcess, ev.request_id, "error", "Unsupported request: " + req.subtype);
            }
        } else if (ev.type === "control_cancel_request") {
            permissionQueue = permissionQueue.filter(function(p) { return p.requestId !== ev.request_id; });
        } else if (ev.type === "assistant") {
            for (var i = 0; i < content.length; i++) {
                var block = content[i];
                if (block.type === "thinking") {
                    statusText = tr("status.thinking");
                } else if (block.type === "tool_use") {
                    var newNames = Object.assign({}, _toolNames);
                    newNames[block.id] = block.name;
                    _toolNames = newNames;
                    var step = describeTool(block.name, block.input);
                    addMessage("tool_status", step);
                    statusText = step;
                } else if (block.type === "text" && block.text) {
                    // Some providers send one text block per model turn (or per
                    // streamed chunk) and their "result" carries no answer;
                    // keeping only the last block dropped everything before a
                    // tool call (Kimi, caught reviewing 2026-11-06). The
                    // result's own `result` field still wins in resultText().
                    _lastText = _lastText ? _lastText + "\n\n" + block.text : block.text;
                    statusText = tr("status.writing");
                }
            }
        } else if (ev.type === "user") {
            for (var j = 0; j < content.length; j++) {
                var res = content[j];
                if (res.type !== "tool_result") continue;
                if (res.is_error) {
                    addMessage("tool_status", "✗ " + (_toolNames[res.tool_use_id] || "tool") + " failed");
                }
                statusText = tr(activeEffort !== "" ? "status.thinking" : "status.processing");
            }
        } else if (ev.type === "result") {
            _gotResult = true;
            // Closing stdin lets a confirm-mode agent (which waits for further messages) exit.
            if (_claudeProcess) _claudeProcess.stdinEnabled = false;
            _claudeProcess = null;
            _runningProvider = null;
            permissionQueue = [];
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
        // A run the user stopped ends with a diagnostic error ("[ede_diagnostic]
        // …"): the CLI says the turn was cut short, which is exactly what was
        // asked for. Showing it as a failure would be noise.
        if (_cancelled) {
            var sameProvider = _cancelProvider === providerId;
            _cancelled = false;
            _cancelProvider = "";
            lastCost = "";
            // After a provider switch the answer belongs to the chat that was
            // just cleared: it is dropped, not shown.
            if (sameProvider) finishResponse(tr("status.cancelled"));
            // The cancelled turn was a transfer: its context must survive for
            // a retry (including the message the user sent into it). The temp
            // file itself is already spent — removed, not left behind.
            if (_pendingContextFile !== "") {
                var f = _pendingContextFile;
                _pendingContextFile = "";
                runQuietExit("rm -f " + shellQuote(f), null);
            }
            if (_carriedContext.length > 0) rearmCarriedContext();
            loadHistory();
            return;
        }

        // A failed run echoes back whatever id it was given, including one it
        // could not find. Keeping it would pin every later message to a session
        // that does not exist, and each retry would fail the same way.
        if (data.session_id && !data.is_error) sessionId = data.session_id;
        // Context transfer: a failed or cancelled turn keeps the carried
        // context for a retry (a retry sends the same conversation again);
        // a success drops it — the native history of the new provider takes
        // over. The temp file is removed either way.
        if (data.is_error) {
            if (_carriedContext.length > 0) rearmCarriedContext();
            removeContextFile();
        } else {
            clearChatContext();
        }
        // The cost line belongs to the providers that report a price. Qoder and
        // Kimi answer with total_cost_usd 0 and empty token counts — "$0.0000
        // (0→0 tokens)" is noise, not a price.
        lastCost = "";
        var costKnown = providerOrClaude.caps && providerOrClaude.caps.cost;
        var cost = data.total_cost_usd;
        var tokens = data.usage;
        var tokensKnown = tokens && ((tokens.input_tokens || 0) + (tokens.output_tokens || 0) > 0);
        if (costKnown && cost !== undefined && cost > 0) {
            lastCost = "$" + cost.toFixed(4);
            if (tokensKnown) {
                lastCost += " (" + (tokens.input_tokens || 0) + "→" + (tokens.output_tokens || 0) + " tokens)";
            }
        }

        var response = Providers.resultText(data, _lastText);
        finishResponse(response || "(done)");
        if (data.session_id && providerOrClaude.caps && providerOrClaude.caps.registryHistory) {
            // Qoder and Kimi leave no scannable trace of what this chat ran, so
            // the registry gets the id the moment it appears — and keeps it:
            // an existing entry holds the title the user may have renamed.
            var title = "";
            for (var i = 0; i < messages.length; i++) {
                if (messages[i].role === "user") { title = String(messages[i].content || ""); break; }
            }
            runQuietExit(cdWorkDir + "python3 " + shellQuote(historyScript) + " --provider " + shellQuote(providerId) + " register " + shellQuote(data.session_id) + " " + shellQuote(title), function() {
                loadHistory();
            });
        } else {
            loadHistory();
        }
    }

    function finishResponse(text, transferError) {
        var msg = addMessage("assistant", text);
        if (transferError) msg.transferError = true;
        busy = false; statusText = tr("status.ready");
        responseComplete(); notifyIfHidden(text);
    }
}
