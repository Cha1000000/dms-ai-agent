import QtQuick
import QtQuick.Layouts
import Quickshell.Io
import Quickshell
import Quickshell.Services.Pipewire
import qs.Common
import qs.Widgets
import qs.DCommon.Widgets
import qs.Modules.Plugins
import "providers.js" as Providers
import "i18n.js" as I18n

PluginSettings {
    id: root
    pluginId: "dmsAgent"

    // The interface language, the same rule the chat uses: the Language
    // setting is about speech recognition, but someone who fixes it to their
    // own language means the plugin to speak it too. Left on "auto" the
    // interface follows the locale. The page reads the setting itself: unlike
    // the chat it has no live property handed down by DmsAgent.qml.
    property string languageSetting: "auto"
    readonly property string uiLanguage: {
        var lang = (languageSetting && languageSetting !== "auto") ? languageSetting : "";
        if (!lang) {
            var env = Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES")
                        || Quickshell.env("LANG") || "";
            lang = String(env).substring(0, 2);
        }
        return String(lang).toLowerCase();
    }
    function reloadLanguage() {
        languageSetting = loadValue("voiceLanguage", "auto");
    }
    // PluginSettings already defines Component.onCompleted and
    // onPluginServiceChanged (variants, child reloads); redefining either here
    // would override them. A 0 ms timer and a change of our own flag do the
    // post-init read instead.
    property bool serviceReady: pluginService !== null
    onServiceReadyChanged: {
        Qt.callLater(reloadLanguage);
        // The stored provider can only be resolved once plugin data is here:
        // a registry id read earlier falls back to the default label.
        if (serviceReady) Qt.callLater(function() { providerSelect.loadValue(); });
    }
    Timer {
        interval: 0
        running: true
        onTriggered: root.reloadLanguage()
    }
    Connections {
        target: root.pluginService
        enabled: root.pluginService !== null
        function onPluginDataChanged(changedPluginId) {
            if (changedPluginId !== root.pluginId)
                return;
            root.reloadLanguage();
            // The chat also changes claudeModel on its own: restoring the
            // provider's saved model, or replacing a foreign id with one from
            // the provider's catalog. Follow it, unless the field is focused.
            if (modelSetting)
                Qt.callLater(modelSetting.loadValue);
        }
    }

    // Microphones offered in the dropdown. Sinks are outputs and streams are
    // individual apps, so both are filtered out; what is left are capture devices.
    // The label is what the audio settings show, the stored value is the node
    // name, which is what pw-record takes as --target.
    readonly property var micNodes: Pipewire.nodes.values.filter(n => n && n.audio && !n.isSink && !n.isStream)

    readonly property var micOptions: {
        const list = [{ label: I18n.t(root.uiLanguage, "settings.mic.default"), value: "" }];
        for (const node of micNodes)
            list.push({ label: micLabel(node), value: node.name });
        return list;
    }

    // Agent CLIs the chat can run. Providers.js is the registry; adding one there
    // is enough for it to show up here and in the model picker.
    property var externalProviders: ({})
    // SelectionSetting resolves its stored value against the options it has at
    // that moment. Registry providers arrive later (registry.py is a Process),
    // so a saved "opencode-acp" fell back to the default label and the "in use"
    // badge had nothing to match. Re-read once the list is complete.
    onExternalProvidersChanged: Qt.callLater(function() { providerSelect.loadValue(); })
    readonly property var providerOptions: {
        const list = [];
        for (const p of Providers.all())
            list.push({ label: p.title, value: p.id });
        for (const id of Object.keys(externalProviders)) {
            const p = externalProviders[id];
            if (p && ["acp", "codex", "claude-cli", "openai"].indexOf(p.adapter) >= 0)
                list.push({ label: p.title || id, value: id });
        }
        return list;
    }

    // Ask-first needs the can_use_tool handshake; Qoder and CVC do not speak it,
    // so those providers only offer "No confirmation".
    readonly property bool providerCanAskFirst: {
        const p = Providers.byId(providerSelect.value || "claude");
        return !!(p && p.caps && p.caps.askFirst);
    }
    readonly property var permissionModeOptions: {
        if (providerCanAskFirst)
            return [
                { label: I18n.t(root.uiLanguage, "settings.permissions.ask"), value: "confirm" },
                { label: I18n.t(root.uiLanguage, "settings.permissions.auto"), value: "auto" }
            ];
        return [{ label: I18n.t(root.uiLanguage, "settings.permissions.autoOnly"), value: "auto" }];
    }
    readonly property string permissionModeDesc: {
        return I18n.t(root.uiLanguage, providerCanAskFirst
                      ? "settings.permissions.descAsk" : "settings.permissions.descAuto");
    }

    // The mode is kept per provider. Forcing "auto" into the single stored key
    // whenever a provider without the handshake was selected silently
    // downgraded the user's Ask-first preference for Claude Code after a visit
    // to Qoder, and nothing ever restored it.
    Connections {
        target: providerSelect
        function onValueChanged() {
            const map = root.loadValue("permissionModes", {}) || {};
            const canAsk = providerCanAskFirst;
            const want = map[providerSelect.value] !== undefined
                    ? map[providerSelect.value]
                    : (canAsk ? "confirm" : "auto");
            if (permissionSelect.value !== want)
                permissionSelect.value = want;
            // The model is per provider too, and StringSetting reads its value
            // once at creation: without this the field kept the previous
            // provider's id while the chat already used the restored one.
            Qt.callLater(modelSetting.loadValue);
        }
    }

    function micLabel(node) {
        const props = node.properties || {};
        return props["node.description"] || node.description || node.nickname || node.name;
    }

    // SliderSetting reads its stored value synchronously in Component.onCompleted,
    // before the host has handed over pluginService, so it silently keeps the
    // default and shows it after the settings are reopened (String/Toggle settings
    // defer the read with Qt.callLater and are fine). Do the same here.
    component SavedSlider: SliderSetting {
        Component.onCompleted: Qt.callLater(loadValue)
    }

    // SelectionSetting reads synchronously too and shows its default after reopening.
    component SavedSelection: SelectionSetting {
        Component.onCompleted: Qt.callLater(loadValue)
    }

    // The CheapVibeCode API key. Lives in ~/.local/state/dms-agent/providers.json
    // (0600) via provider_secrets.py — not in plugin settings, which ccsync
    // copies between machines. "Test" hits GET /v1/models with the stored key.
    component CvcKeySetting: Column {
        id: cvcKey
        width: parent.width
        spacing: Theme.spacingS

        readonly property string secretsScript: decodeURIComponent(String(Qt.resolvedUrl("provider_secrets.py")).replace(/^file:\/\//, ""))
        property string keyStatus: ""

        function loadStatus() {
            keyCheck.running = true;
        }
        Component.onCompleted: Qt.callLater(loadStatus)

        Process {
            id: keyCheck
            command: ["python3", cvcKey.secretsScript, "check", "cvc"]
            stdout: StdioCollector {
                onStreamFinished: cvcKey.keyStatus = String(text).trim()
            }
        }
        Process {
            id: keySave
            // The key goes in through stdin, never as an argument: a command
            // line is readable by any user of the machine in /proc/<pid>/cmdline.
            property string pendingKey: ""
            command: ["python3", cvcKey.secretsScript, "set", "cvc"]
            stdinEnabled: true
            onStarted: {
                write(pendingKey + "\n");
                stdinEnabled = false;
                pendingKey = "";
            }
            stdout: StdioCollector {
                onStreamFinished: {
                    cvcKey.keyResult = String(text).trim() === "ok"
                            ? I18n.t(root.uiLanguage, "settings.cvc.saved")
                            : I18n.t(root.uiLanguage, "settings.cvc.saveFailed");
                    cvcKey.loadStatus();
                }
            }
        }
        Process {
            id: keyTest
            command: ["python3", cvcKey.secretsScript, "test", "cvc"]
            stdout: StdioCollector {
                onStreamFinished: {
                    const out = String(text).trim();
                    if (out.indexOf("ok ") === 0)
                        cvcKey.keyResult = I18n.t(root.uiLanguage, "settings.cvc.works",
                                                  { n: out.substring(3) });
                    else if (out === "missing")
                        cvcKey.keyResult = I18n.t(root.uiLanguage, "settings.cvc.missing");
                    else
                        cvcKey.keyResult = out;
                }
            }
        }
        property string keyResult: ""

        StyledText {
            text: I18n.t(root.uiLanguage, "settings.cvc.title")
            font.pixelSize: Theme.fontSizeMedium
            font.weight: Font.Medium
            color: Theme.surfaceText
        }
        StyledText {
            text: I18n.t(root.uiLanguage, "settings.cvc.desc")
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.surfaceVariantText
            width: parent.width
            wrapMode: Text.WordWrap
        }

        Row {
            width: parent.width
            spacing: Theme.spacingM

            DankTextField {
                id: keyField
                width: parent.width - saveBtn.width - testBtn.width - Theme.spacingM * 2
                placeholderText: cvcKey.keyStatus === "set"
                                 ? I18n.t(root.uiLanguage, "settings.cvc.savedPlaceholder")
                                 : I18n.t(root.uiLanguage, "settings.cvc.placeholder")
                showPasswordToggle: true
                echoMode: TextInput.Password
            }
            DankButton {
                id: saveBtn
                text: I18n.t(root.uiLanguage, "settings.cvc.save")
                onClicked: {
                    if (keyField.text.trim() === "") return;
                    keySave.pendingKey = keyField.text.trim();
                    keyField.text = "";
                    keySave.running = true;
                }
            }
            DankButton {
                id: testBtn
                text: I18n.t(root.uiLanguage, "settings.cvc.test")
                onClicked: {
                    cvcKey.keyResult = I18n.t(root.uiLanguage, "settings.cvc.checking");
                    // models.py --provider cvc refreshes the cache and fails when
                    // the key is missing or rejected; that is the validation.
                    keyTest.running = true;
                }
            }
        }
        StyledText {
            text: cvcKey.keyResult
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.surfaceVariantText
            visible: cvcKey.keyResult !== ""
        }
    }

    // --- External provider registry (providers.json) ---
    // The form writes through registry.py; the JSON editor edits the same
    // entries. Keys are never shown here: they live in the registry's "keys"
    // section, managed via provider_secrets.py (the CvcKeySetting pattern).
    readonly property string registryScript: decodeURIComponent(String(Qt.resolvedUrl("registry.py")).replace(/^file:\/\//, ""))

    component RegistryProviders: Column {
        id: regProviders
        width: parent ? parent.width : 0
        spacing: Theme.spacingM

        property var providers: ({})
        // The provider the chat is set to: the row list badges it.
        property string activeProviderId: ""
        property bool loadFailed: false
        property string loadError: ""
        property bool registryLoaded: false
        property string editorId: ""
        property bool jsonMode: false
        property string formError: ""
        property string listError: ""
        property var pendingEntry: null
        property string pendingId: ""
        property string pendingKey: ""
        property string pendingCommandText: ""
        property string pendingUrlValue: ""
        property bool pendingNeedsUrl: false
        readonly property string registryPath: Quickshell.env("PROVIDER_REGISTRY")
            || ((Quickshell.env("XDG_STATE_HOME")
                 || (Quickshell.env("HOME") + "/.local/state")) + "/dms-agent/providers.json")

        // The chat watches the same file; without a watcher here a provider
        // added from the CLI (or another window) stayed invisible until the
        // settings page was reopened.
        FileView {
            path: regProviders.registryPath
            watchChanges: true
            onFileChanged: regProviders.reload()
        }

        function reload() {
            if (listProc.running) return;
            registryLoaded = false;
            listProc.command = ["python3", root.registryScript, "list", "--json"];
            listProc.running = true;
        }
        Component.onCompleted: Qt.callLater(reload)

        Process {
            id: listProc
            // The python reason (corrupt file, unsupported version) is on
            // stderr; without this the UI showed a bare JSON parse error.
            stderr: StdioCollector {
                onStreamFinished: regProviders.listError = String(text).trim()
            }
            stdout: StdioCollector {
                onStreamFinished: {
                    const reason = regProviders.listError;
                    regProviders.listError = "";
                    try {
                        const data = JSON.parse(String(text).trim());
                        if (!data || !data.providers || typeof data.providers !== "object" || Array.isArray(data.providers))
                            throw new Error("invalid providers section");
                        regProviders.providers = data.providers;
                        root.externalProviders = regProviders.providers;
                        regProviders.loadFailed = false;
                        regProviders.registryLoaded = true;
                        regProviders.loadError = "";
                    } catch (e) {
                        regProviders.loadFailed = true;
                        regProviders.loadError = reason || String(text).trim() || String(e);
                    }
                }
            }
        }

        function saveProvider(pid, entry) {
            if (saveProc.running || keyProc.running) return;
            saveProc.pendingId = pid;
            saveProc.pendingEntry = JSON.stringify(entry);
            saveProc.errorText = "";
            saveProc.stdinEnabled = true;
            saveProc.running = true;
        }
        Process {
            id: saveProc
            property string pendingId: ""
            property string pendingEntry: ""
            property string errorText: ""
            command: ["python3", root.registryScript, "set-provider", pendingId]
            stdinEnabled: true
            onStarted: {
                write(pendingEntry);
                stdinEnabled = false;
            }
            stderr: StdioCollector { onStreamFinished: saveProc.errorText = String(text).trim() }
            onExited: (exitCode, exitStatus) => {
                if (exitCode !== 0 || exitStatus !== 0) {
                    regProviders.formError = I18n.t(root.uiLanguage, "settings.reg.saveFailed") + " " + errorText;
                    regProviders.pendingKey = "";
                    return;
                }
                regProviders.formError = "";
                if (regProviders.pendingKey !== "") {
                    regProviders.setKey(pendingId, regProviders.pendingKey);
                    regProviders.pendingKey = "";
                    formKeyField.text = "";
                    // The key write can still fail: keep the form (and its
                    // error line) in place until keyProc answers.
                } else {
                    // The entry is written: fold the form and show the row.
                    regProviders.cancelForm();
                }
                regProviders.reload();
            }
        }

        function removeProvider(pid) {
            removeProc.pendingId = pid;
            removeProc.running = true;
        }
        Process {
            id: removeProc
            property string pendingId: ""
            command: ["python3", root.registryScript, "remove-provider", pendingId]
            property string errorText: ""
            stderr: StdioCollector { onStreamFinished: removeProc.errorText = String(text).trim() }
            onExited: (exitCode, exitStatus) => {
                if (exitCode !== 0 || exitStatus !== 0) {
                    regProviders.loadFailed = true;
                    regProviders.loadError = errorText;
                    return;
                }
                if (regProviders.editorId === removeProc.pendingId) regProviders.cancelForm();
                regProviders.reload();
            }
        }

        // Keys for registry providers that need one (openai gateways). Same
        // channel as CvcKeySetting: stdin, never argv.
        function setKey(pid, key) {
            keyProc.pendingId = pid;
            keyProc.pendingKey = key;
            keyProc.errorText = "";
            keyProc.stdinEnabled = true;
            keyProc.running = true;
        }
        Process {
            id: keyProc
            property string pendingId: ""
            property string pendingKey: ""
            property string errorText: ""
            command: ["python3", root.registryScript, "set-key", pendingId]
            stdinEnabled: true
            onStarted: {
                write(pendingKey + "\n");
                pendingKey = "";
                stdinEnabled = false;
            }
            stderr: StdioCollector { onStreamFinished: keyProc.errorText = String(text).trim() }
            onExited: (exitCode, exitStatus) => {
                if (exitCode !== 0 || exitStatus !== 0)
                    regProviders.formError = I18n.t(root.uiLanguage, "settings.reg.keySaveFailed") + " " + errorText;
            }
        }

        // --- Add / edit form ---
        property string formId: ""        // "" = new
        property string pendingEditId: ""
        // The form is folded away until the user asks for it: a permanent
        // "New provider" block under the list made the header button look dead
        // (it only cleared an already empty form).
        property bool formVisible: false
        // Which field the last validation error belongs to: "" = a general
        // save error, otherwise the error sits under id/command/url.
        property string fieldError: ""
        property string fieldErrorField: ""

        function clearFieldError() {
            fieldError = "";
            fieldErrorField = "";
        }
        // validateEntry()/submit() speak in i18n keys; the form shows the text
        // under the offending field instead of one line below the buttons.
        function errorFieldFor(code) {
            if (code === "settings.reg.badId" || code === "settings.reg.reservedId"
                || code === "settings.reg.idConflict") return "id";
            if (code === "settings.reg.badUrl") return "url";
            if (code === "settings.reg.needCommand") return "command";
            return "";
        }
        function setFieldError(code) {
            formError = I18n.t(root.uiLanguage, code);
            fieldError = formError;
            fieldErrorField = errorFieldFor(code);
        }
        function startEdit(pid) {
            jsonMode = false;
            const e = providers[pid] || {};
            formId = pid;
            // A key typed for another provider must never be saved to this one.
            formKeyField.text = "";
            pendingEditId = pid;
            formAdapter = e.adapter || "acp";
            formTitle = e.title || "";
            formCommand = Array.isArray(e.command) ? e.command.join(" ") : String(e.command || "");
            formBaseUrl = e.baseUrl || "";
            formError = "";
            clearFieldError();
            formVisible = true;
        }
        function startNew() {
            jsonMode = false;
            formKeyField.text = "";
            formId = "";
            pendingEditId = "";
            formAdapter = "acp";
            formTitle = "";
            formCommand = "";
            formBaseUrl = "";
            formError = "";
            clearFieldError();
            formVisible = true;
        }
        function cancelForm() {
            jsonMode = false;
            formVisible = false;
            // A pending confirmation must not outlive the form it belonged to.
            confirmCommandDialog.visible = false;
            confirmUrlDialog.visible = false;
            formKeyField.text = "";
            formId = "";
            pendingEditId = "";
            formTitle = "";
            formCommand = "";
            formBaseUrl = "";
            formError = "";
            clearFieldError();
        }
        function validateEntry(pid, entry) {
            if (!/^[a-z0-9-]+$/.test(pid)) return "settings.reg.badId";
            // A registry id must not shadow a built-in provider: registry.py
            // refuses it too, but the form should say so before a round trip.
            if (Providers.all().some(p => p.id === pid)) return "settings.reg.reservedId";
            if (!entry || typeof entry !== "object" || Array.isArray(entry)) return "settings.reg.badEntry";
            if (Object.keys(entry).some(k => ["adapter", "title", "command", "baseUrl"].indexOf(k) < 0))
                return "settings.reg.badFields";
            if (["acp", "codex", "claude-cli", "openai"].indexOf(entry.adapter) < 0) return "settings.reg.badAdapter";
            if (entry.title !== undefined && typeof entry.title !== "string") return "settings.reg.badEntry";
            if (entry.adapter === "openai") {
                if (entry.command !== undefined || typeof entry.baseUrl !== "string") return "settings.reg.badEntry";
                const url = entry.baseUrl.trim().replace(/\/+$/, "");
                if (!/^(https:\/\/[a-z0-9.-]+(?::[0-9]+)?|https:\/\/\[[0-9a-f:]+\](?::[0-9]+)?|http:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?)(?:\/[a-z0-9._~!$&'()*+,;=:@%/-]*)?$/i.test(url))
                    return "settings.reg.badUrl";
                entry.baseUrl = url;
            } else {
                if (entry.baseUrl !== undefined || !Array.isArray(entry.command) || !entry.command.length
                    || entry.command.some(x => typeof x !== "string" || !x.length || /[\x00-\x1f\x7f]/.test(x)))
                    return "settings.reg.needCommand";
            }
            return "";
        }
        function prepareSave(pid, entry, key) {
            if (!registryLoaded || loadFailed || saveProc.running || keyProc.running) return;
            const error = validateEntry(pid, entry);
            if (error) {
                if (jsonMode) formError = I18n.t(root.uiLanguage, error);
                else setFieldError(error);
                return;
            }
            const old = providers[pid] || null;
            pendingId = pid;
            pendingEntry = entry;
            pendingKey = key;
            pendingCommandText = entry.command ? JSON.stringify(entry.command, null, 2) : "";
            pendingUrlValue = entry.baseUrl || "";
            pendingNeedsUrl = entry.adapter === "openai" && (!old || old.baseUrl !== entry.baseUrl);
            formError = "";
            clearFieldError();
            if (entry.command && (!old || JSON.stringify(old.command) !== JSON.stringify(entry.command)))
                confirmCommandDialog.visible = true;
            else
                confirmNext();
        }
        function confirmNext() {
            if (pendingNeedsUrl) {
                pendingNeedsUrl = false;
                confirmUrlDialog.visible = true;
            } else {
                saveProvider(pendingId, pendingEntry);
            }
        }
        function submit() {
            const pid = formId.trim();
            if ((pendingEditId && pid !== pendingEditId) || (!pendingEditId && Object.prototype.hasOwnProperty.call(providers, pid))) {
                setFieldError("settings.reg.idConflict");
                return;
            }
            const entry = Object.assign({}, providers[pid] || {});
            entry.adapter = formAdapter;
            entry.title = formTitle.trim() || pid;
            if (formAdapter === "openai") {
                delete entry.command;
                entry.baseUrl = formBaseUrl;
            } else {
                delete entry.baseUrl;
                entry.command = formCommand.trim().split(/\s+/).filter(Boolean);
            }
            prepareSave(pid, entry, formKeyField.text.trim());
        }
        function openJson(pid) {
            editorId = pid;
            jsonMode = true;
            formError = "";
            const entry = providers[pid];
            if (!entry || typeof entry !== "object" || Array.isArray(entry)
                || Object.keys(entry).some(k => ["adapter", "title", "command", "baseUrl"].indexOf(k) < 0)) {
                jsonEntry.text = "";
                formError = I18n.t(root.uiLanguage, "settings.reg.badFields");
                return;
            }
            jsonEntry.text = JSON.stringify(entry, null, 2);
        }
        function submitJson() {
            let entry;
            try {
                entry = JSON.parse(jsonEntry.text);
            } catch (e) {
                formError = I18n.t(root.uiLanguage, "settings.reg.badJson") + " " + String(e);
                return;
            }
            prepareSave(editorId, entry, "");
        }
        function commandText(e) {
            return Array.isArray(e.command) ? e.command.join(" ") : String(e.command || "");
        }

        property string formAdapter: "acp"
        property string formTitle: ""
        property string formCommand: ""
        property string formBaseUrl: ""

        RowLayout {
            width: parent.width
            spacing: Theme.spacingS
            StyledText {
                text: I18n.t(root.uiLanguage, "settings.reg.title")
                font.pixelSize: Theme.fontSizeMedium
                font.weight: Font.Bold
                color: Theme.surfaceText
                Layout.fillWidth: true
            }
            DankButton {
                // Opens the form below; without this the section had two
                // identical "Add" buttons and the header one did nothing.
                text: I18n.t(root.uiLanguage, "settings.reg.addProvider")
                onClicked: regProviders.startNew()
            }
        }

        StyledText {
            visible: regProviders.loadFailed
            width: parent.width
            wrapMode: Text.WordWrap
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.withAlpha(Theme.error, 0.9)
            text: I18n.t(root.uiLanguage, "settings.reg.loadFailed") + " " + regProviders.loadError
        }

        // --- Add / edit form ---
        // Above the list and folded away until asked for: the form used to sit
        // under the rows, always open, so the header button looked dead and the
        // editor could open off-screen.
        Column {
            width: parent.width
            spacing: Theme.spacingS
            visible: regProviders.formVisible && !regProviders.jsonMode
            // Opening the form must land the caret in the first field: a form
            // that appears without focus made the header button look half-done
            // and left the user to click the field themselves.
            // Opening the form must land the caret in the first field: a form
            // that appears without focus made the header button look half-done
            // and left the user to click the field themselves.
            onVisibleChanged: if (visible) Qt.callLater(function() { formIdField.forceActiveFocus(); })

            StyledText {
                width: parent.width
                text: regProviders.pendingEditId === ""
                      ? I18n.t(root.uiLanguage, "settings.reg.newProvider")
                      : I18n.t(root.uiLanguage, "settings.reg.editing") + " " + regProviders.pendingEditId
                font.pixelSize: Theme.fontSizeMedium
                font.weight: Font.Medium
                color: Theme.surfaceText
            }

            // What the adapter choice means: read it before picking one, not
            // after the buttons.
            StyledText {
                width: parent.width
                wrapMode: Text.WordWrap
                text: I18n.t(root.uiLanguage, "settings.reg.hint")
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceVariantText
            }

            RowLayout {
                width: parent.width
                spacing: Theme.spacingS
                DankTextField {
                    id: formIdField
                    Layout.fillWidth: true
                    placeholderText: I18n.t(root.uiLanguage, "settings.reg.idPlaceholder")
                    text: regProviders.formId
                    enabled: regProviders.pendingEditId === ""
                    onTextEdited: {
                        regProviders.formId = text;
                        regProviders.clearFieldError();
                    }
                }
                DDropdown {
                    id: formAdapterSelect
                    width: 160
                    text: ""
                    currentValue: regProviders.formAdapter === "acp" ? "ACP"
                                  : regProviders.formAdapter === "codex" ? "Codex"
                                  : regProviders.formAdapter === "claude-cli" ? "Claude CLI"
                                  : "OpenAI gateway"
                    options: ["ACP", "Codex", "Claude CLI", "OpenAI gateway"]
                    onValueChanged: newValue => {
                        regProviders.formAdapter = newValue === "ACP" ? "acp"
                            : newValue === "Codex" ? "codex"
                            : newValue === "Claude CLI" ? "claude-cli" : "openai";
                        regProviders.clearFieldError();
                    }
                }
            }

            StyledText {
                visible: regProviders.fieldErrorField === "id"
                width: parent.width
                wrapMode: Text.WordWrap
                text: regProviders.fieldError
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.withAlpha(Theme.error, 0.9)
            }

            DankTextField {
                id: formTitleField
                width: parent.width
                placeholderText: I18n.t(root.uiLanguage, "settings.reg.titlePlaceholder")
                text: regProviders.formTitle
                onTextEdited: regProviders.formTitle = text
            }

            DankTextField {
                id: formCommandField
                width: parent.width
                visible: regProviders.formAdapter !== "openai"
                placeholderText: I18n.t(root.uiLanguage, "settings.reg.commandPlaceholder")
                text: regProviders.formCommand
                onTextEdited: {
                    regProviders.formCommand = text;
                    regProviders.clearFieldError();
                }
            }

            StyledText {
                visible: regProviders.fieldErrorField === "command"
                width: parent.width
                wrapMode: Text.WordWrap
                text: regProviders.fieldError
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.withAlpha(Theme.error, 0.9)
            }

            DankTextField {
                id: formUrlField
                width: parent.width
                visible: regProviders.formAdapter === "openai"
                placeholderText: I18n.t(root.uiLanguage, "settings.reg.urlPlaceholder")
                text: regProviders.formBaseUrl
                onTextEdited: {
                    regProviders.formBaseUrl = text;
                    regProviders.clearFieldError();
                }
            }

            StyledText {
                visible: regProviders.fieldErrorField === "url"
                width: parent.width
                wrapMode: Text.WordWrap
                text: regProviders.fieldError
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.withAlpha(Theme.error, 0.9)
            }

            DankTextField {
                id: formKeyField
                width: parent.width
                // Only the OpenAI gateway bridge reads a key; an ACP/Codex
                // entry would store a secret nothing uses.
                visible: regProviders.formAdapter === "openai"
                placeholderText: I18n.t(root.uiLanguage, "settings.reg.keyPlaceholder")
                showPasswordToggle: true
                echoMode: TextInput.Password
            }

            // Save failures (write error, key error) have no field: they stay
            // in one line above the buttons.
            StyledText {
                visible: regProviders.formError !== "" && regProviders.fieldErrorField === ""
                width: parent.width
                wrapMode: Text.WordWrap
                text: regProviders.formError
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.withAlpha(Theme.error, 0.9)
            }

            Row {
                spacing: Theme.spacingS
                DankButton {
                    text: regProviders.pendingEditId === ""
                          ? I18n.t(root.uiLanguage, "settings.reg.add")
                          : I18n.t(root.uiLanguage, "settings.reg.save")
                    enabled: regProviders.registryLoaded && !regProviders.loadFailed && !saveProc.running && !keyProc.running
                    onClicked: regProviders.submit()
                }
                DankButton {
                    text: I18n.t(root.uiLanguage, "settings.reg.cancel")
                    onClicked: regProviders.cancelForm()
                }
            }
        }

        // --- JSON editor: one entry, never the keys section ---
        Column {
            width: parent.width
            spacing: Theme.spacingS
            visible: regProviders.jsonMode
            StyledText {
                width: parent.width
                wrapMode: Text.WordWrap
                text: I18n.t(root.uiLanguage, "settings.reg.jsonHint") + " " + regProviders.editorId
                color: Theme.surfaceVariantText
                font.pixelSize: Theme.fontSizeSmall
            }
            DankTextEdit {
                id: jsonEntry
                width: parent.width
                height: 240
                textColor: Theme.surfaceText
                font.pixelSize: Theme.fontSizeSmall
            }
            StyledText {
                visible: regProviders.formError !== ""
                width: parent.width
                wrapMode: Text.WordWrap
                text: regProviders.formError
                color: Theme.withAlpha(Theme.error, 0.9)
                font.pixelSize: Theme.fontSizeSmall
            }
            Row {
                spacing: Theme.spacingS
                DankButton {
                    text: I18n.t(root.uiLanguage, "settings.reg.save")
                    enabled: regProviders.registryLoaded && !regProviders.loadFailed && !saveProc.running && !keyProc.running
                    onClicked: regProviders.submitJson()
                }
                DankButton {
                    text: I18n.t(root.uiLanguage, "settings.reg.cancel")
                    onClicked: regProviders.cancelForm()
                }
            }
        }

        // Confirmations for the form sit right under it: a card placed after
        // the provider list opened off-screen and looked like nothing happened.
        // Command-change confirmation: the new argv will be executed as-is.
        Rectangle {
            id: confirmCommandDialog
            visible: false
            width: parent.width
            height: cmdCol.implicitHeight + Theme.spacingM * 2
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHighest
            border.width: 1
            border.color: Theme.withAlpha(Theme.primary, 0.45)
            Column {
                id: cmdCol
                x: Theme.spacingM
                y: Theme.spacingM
                width: parent.width - Theme.spacingM * 2
                spacing: Theme.spacingS
                StyledText {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: I18n.t(root.uiLanguage, "settings.reg.confirmCommand") + "\n" + regProviders.pendingCommandText
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.surfaceText
                }
                Row {
                    spacing: Theme.spacingS
                    DankButton {
                        text: I18n.t(root.uiLanguage, "settings.reg.cancel")
                        onClicked: confirmCommandDialog.visible = false
                    }
                    DankButton {
                        text: I18n.t(root.uiLanguage, "settings.reg.confirm")
                        onClicked: {
                            confirmCommandDialog.visible = false;
                            regProviders.confirmNext();
                        }
                    }
                }
            }
        }

        // URL-change confirmation: the stored API key would be sent to a new origin.
        Rectangle {
            id: confirmUrlDialog
            visible: false
            width: parent.width
            height: urlCol.implicitHeight + Theme.spacingM * 2
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHighest
            border.width: 1
            border.color: Theme.withAlpha(Theme.primary, 0.45)
            Column {
                id: urlCol
                x: Theme.spacingM
                y: Theme.spacingM
                width: parent.width - Theme.spacingM * 2
                spacing: Theme.spacingS
                StyledText {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: I18n.t(root.uiLanguage, "settings.reg.confirmUrl") + "\n" + regProviders.pendingUrlValue
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.surfaceText
                }
                Row {
                    spacing: Theme.spacingS
                    DankButton {
                        text: I18n.t(root.uiLanguage, "settings.reg.cancel")
                        onClicked: confirmUrlDialog.visible = false
                    }
                    DankButton {
                        text: I18n.t(root.uiLanguage, "settings.reg.confirm")
                        onClicked: {
                            confirmUrlDialog.visible = false;
                            regProviders.confirmNext();
                        }
                    }
                }
            }
        }

        // Rows: one per registry provider.
        Column {
            width: parent.width
            spacing: Theme.spacingXS
            visible: Object.keys(regProviders.providers).length > 0

            Repeater {
                model: Object.keys(regProviders.providers)
                delegate: Rectangle {
                    id: regRow
                    required property string modelData
                    readonly property var entry: regProviders.providers[modelData] || {}
                    width: parent.width
                    height: regRowInner.implicitHeight + Theme.spacingS * 2
                    radius: Theme.cornerRadius
                    color: Theme.withAlpha(Theme.surfaceVariant, 0.3)

                    Column {
                        id: regRowInner
                        anchors.fill: parent
                        anchors.margins: Theme.spacingS
                        spacing: Theme.spacingXXS

                        RowLayout {
                            width: parent.width
                            spacing: Theme.spacingS
                            StyledText {
                                text: modelData
                                font.pixelSize: Theme.fontSizeSmall
                                font.weight: Font.Medium
                                color: Theme.surfaceText
                                Layout.fillWidth: true
                                wrapMode: Text.NoWrap
                                elide: Text.ElideRight
                            }
                            // Which provider the chat runs: without this the
                            // list gave no sign that one of the rows is active.
                            StyledText {
                                visible: modelData === regProviders.activeProviderId
                                text: I18n.t(root.uiLanguage, "settings.reg.inUse")
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.primary
                                wrapMode: Text.NoWrap
                                Layout.alignment: Qt.AlignVCenter
                            }
                            StyledText {
                                text: regRow.entry.adapter || ""
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.surfaceVariantText
                            }
                        }

                        // Executed program / gateway address, visible without opening the editor.
                        StyledText {
                            visible: Array.isArray(regRow.entry.command)
                            width: parent.width
                            text: I18n.t(root.uiLanguage, "settings.reg.runs") + " " + regProviders.commandText(regRow.entry)
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                            elide: Text.ElideMiddle
                        }
                        StyledText {
                            visible: !!regRow.entry.baseUrl
                            width: parent.width
                            text: I18n.t(root.uiLanguage, "settings.reg.gateway") + " " + regRow.entry.baseUrl
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                            elide: Text.ElideMiddle
                        }

                        // Actions on their own line: inline with the id they
                        // overran the row and the button covered the JSON link.
                        Row {
                            anchors.right: parent.right
                            spacing: Theme.spacingS
                            // The everyday action carries the button; JSON and
                            // removal stay quiet links so the eye lands on "Edit".
                            DankButton {
                                text: I18n.t(root.uiLanguage, "settings.reg.edit")
                                onClicked: regProviders.startEdit(modelData)
                            }
                            Rectangle {
                                width: jsonRow.width + Theme.spacingS; height: Theme.iconSize
                                radius: Theme.cornerRadius
                                color: jsonArea.containsMouse ? Theme.withAlpha(Theme.primary, 0.2) : "transparent"
                                Row {
                                    id: jsonRow
                                    anchors.centerIn: parent
                                    spacing: Theme.spacingXXS
                                    DankIcon { name: "code"; size: Theme.iconSizeSmall; color: jsonArea.containsMouse ? Theme.primary : Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                                    StyledText { text: I18n.t(root.uiLanguage, "settings.reg.jsonEdit"); font.pixelSize: Theme.fontSizeSmall; color: jsonArea.containsMouse ? Theme.primary : Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                                }
                                MouseArea {
                                    id: jsonArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: regProviders.openJson(modelData)
                                }
                            }
                            Rectangle {
                                width: delRow.width + Theme.spacingS; height: Theme.iconSize
                                radius: Theme.cornerRadius
                                color: delArea.containsMouse ? Theme.withAlpha(Theme.danger, 0.2) : "transparent"
                                Row {
                                    id: delRow
                                    anchors.centerIn: parent
                                    spacing: Theme.spacingXXS
                                    DankIcon { name: "delete"; size: Theme.iconSizeSmall; color: delArea.containsMouse ? Theme.danger : Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                                    StyledText { text: I18n.t(root.uiLanguage, "settings.reg.remove"); font.pixelSize: Theme.fontSizeSmall; color: delArea.containsMouse ? Theme.danger : Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                                }
                                MouseArea {
                                    id: delArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        regProviders.confirmRemoveId = modelData;
                                        regProviders.confirmRemoveTitle = regRow.entry.title || modelData;
                                        confirmRemoveDialog.visible = true;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Remove confirmation: the registry entry disappears from this and every
        // future session list; history rows of that provider stop resolving.
        property string confirmRemoveId: ""
        property string confirmRemoveTitle: ""
        Rectangle {
            id: confirmRemoveDialog
            visible: false
            width: parent.width
            height: rmCol.implicitHeight + Theme.spacingM * 2
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHighest
            border.width: 1
            border.color: Theme.withAlpha(Theme.danger, 0.45)
            Column {
                id: rmCol
                x: Theme.spacingM
                y: Theme.spacingM
                width: parent.width - Theme.spacingM * 2
                spacing: Theme.spacingS
                StyledText {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: I18n.t(root.uiLanguage, "settings.reg.confirmRemove") + "\n" + regProviders.confirmRemoveId + " (" + regProviders.confirmRemoveTitle + ")"
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.surfaceText
                }
                Row {
                    spacing: Theme.spacingS
                    DankButton {
                        text: I18n.t(root.uiLanguage, "settings.reg.cancel")
                        onClicked: confirmRemoveDialog.visible = false
                    }
                    DankButton {
                        text: I18n.t(root.uiLanguage, "settings.reg.remove")
                        onClicked: {
                            regProviders.removeProvider(regProviders.confirmRemoveId);
                            confirmRemoveDialog.visible = false;
                        }
                    }
                }
            }
        }

    }

    // Sign-in state of the provider the chat will run. The chat already refuses
    // to start with a hint, but the reason belongs here too — settings is where
    // the user looks before the first message. Each provider checks its own
    // source (OAuth files, an API key, `claude auth status`).
    component ProviderSignIn: Column {
        id: signIn
        width: parent.width
        spacing: Theme.spacingXXS

        // Passed in at the use site: an id from the enclosing file is not visible
        // inside an inline component, and `root.<id>` is not a property at all.
        property string providerId: "claude"
        readonly property string secretsScript: decodeURIComponent(String(Qt.resolvedUrl("provider_secrets.py")).replace(/^file:\/\//, ""))
        // The hint comes from the same table the chat uses, so the two cannot
        // drift apart.
        function hint(provider) {
            const key = Providers.hintKey(Providers.byId(provider));
            return I18n.t(root.uiLanguage, I18n.has(root.uiLanguage, key) ? key : "loginHint.generic");
        }
        property string state: ""      // "set" | "missing" | ""
        property bool refreshQueued: false

        onProviderIdChanged: refresh()
        Component.onCompleted: Qt.callLater(refresh)

        // The command is built here, not bound: a binding on `providerId` is
        // re-evaluated after this change handler, so the first check after a
        // provider switch would still run against the previous provider. A
        // check already in flight is not restarted; the latest provider is
        // checked right after it exits.
        function refresh() {
            if (check.running) {
                refreshQueued = true;
                return;
            }
            check.command = ["python3", secretsScript, "check", providerId];
            check.running = true;
        }

        Process {
            id: check
            onExited: {
                if (signIn.refreshQueued) {
                    signIn.refreshQueued = false;
                    signIn.refresh();
                }
            }
            stdout: StdioCollector {
                onStreamFinished: signIn.state = String(text).trim()
            }
        }

        StyledText {
            visible: signIn.state === "missing"
            width: parent.width
            wrapMode: Text.WordWrap
            font.pixelSize: Theme.fontSizeSmall
            color: Theme.withAlpha(Theme.error, 0.9)
            text: I18n.t(root.uiLanguage, "error.notLoggedIn") + ". " + signIn.hint(signIn.providerId)
        }
    }

    // Properties of a node are only populated while something holds it.
    PwObjectTracker { objects: root.micNodes }

    // Plain Columns, not ColumnLayout: DMS setting widgets size themselves with
    // width: parent.width, which a Layout overrides with their tiny implicit width.
    Column {
        width: parent.width
        spacing: Theme.spacingM

        StyledText {
            text: I18n.t(root.uiLanguage, "settings.title")
            font.pixelSize: Theme.fontSizeLarge
            font.weight: Font.Bold
            color: Theme.surfaceText
        }

        StyledRect {
            width: parent.width
            height: settingsCol.implicitHeight + Theme.spacingL * 2
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHigh

            Column {
                id: settingsCol
                x: Theme.spacingL
                y: Theme.spacingL
                width: parent.width - Theme.spacingL * 2
                spacing: Theme.spacingM

                StyledText {
                    text: I18n.t(root.uiLanguage, "settings.section.provider")
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                RegistryProviders {
                    id: registryProviders
                    activeProviderId: providerSelect.value || "claude"
                }

                SavedSelection {
                    id: providerSelect
                    settingKey: "provider"
                    label: I18n.t(root.uiLanguage, "settings.agent.label")
                    description: I18n.t(root.uiLanguage, "settings.agent.desc")
                    defaultValue: "claude"
                    options: providerOptions
                }

                ProviderSignIn {
                    providerId: providerSelect.value || "claude"
                }

                // CheapVibeCode speaks the Claude Code protocol on their gateway and
                // needs an API key. It is kept out of plugin settings on purpose: those
                // are synced between machines by ccsync, keys must not travel.
                CvcKeySetting {
                    visible: providerSelect.value === "cvc"
                }

                StyledText {
                    text: I18n.t(root.uiLanguage, "settings.section.model")
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                StringSetting {
                    id: modelSetting
                    settingKey: "claudeModel"
                    label: I18n.t(root.uiLanguage, "settings.model.label")
                    description: I18n.t(root.uiLanguage, "settings.model.desc")
                    placeholder: "haiku"
                    defaultValue: "haiku"
                }

                StringSetting {
                    settingKey: "effort"
                    label: I18n.t(root.uiLanguage, "settings.effort.label")
                    description: I18n.t(root.uiLanguage, "settings.effort.desc")
                    placeholder: "auto"
                    defaultValue: ""
                }

                ToggleSetting {
                    settingKey: "restoreSessionModel"
                    label: I18n.t(root.uiLanguage, "settings.sessionModel.label")
                    description: I18n.t(root.uiLanguage, "settings.sessionModel.desc")
                    defaultValue: true
                }

                StringSetting {
                    settingKey: "workDir"
                    label: I18n.t(root.uiLanguage, "settings.workDir.label")
                    description: I18n.t(root.uiLanguage, "settings.workDir.desc")
                    placeholder: "~/projects/my-app"
                    defaultValue: ""
                }

                SavedSelection {
                    id: permissionSelect
                    settingKey: "permissionMode"
                    label: I18n.t(root.uiLanguage, "settings.permissions.label")
                    description: permissionModeDesc
                    defaultValue: "confirm"
                    options: permissionModeOptions
                }

                StringSetting {
                    settingKey: "maxTokens"
                    label: I18n.t(root.uiLanguage, "settings.maxTokens.label")
                    description: I18n.t(root.uiLanguage, "settings.maxTokens.desc")
                    placeholder: "1024"
                    defaultValue: "1024"
                }

                StyledText {
                    text: I18n.t(root.uiLanguage, "settings.section.prompt")
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                    topPadding: Theme.spacingS
                }

                StringSetting {
                    settingKey: "systemPrompt"
                    label: I18n.t(root.uiLanguage, "settings.systemPrompt.label")
                    description: I18n.t(root.uiLanguage, "settings.systemPrompt.desc")
                    placeholder: I18n.t(root.uiLanguage, "settings.systemPrompt.placeholder")
                    defaultValue: ""
                }
            }
        }

        StyledRect {
            width: parent.width
            height: themeCol.implicitHeight + Theme.spacingL * 2
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHigh

            Column {
                id: themeCol
                x: Theme.spacingL
                y: Theme.spacingL
                width: parent.width - Theme.spacingL * 2
                spacing: Theme.spacingM

                StyledText {
                    text: I18n.t(root.uiLanguage, "settings.section.appearance")
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                SavedSelection {
                    settingKey: "themePreset"
                    label: I18n.t(root.uiLanguage, "settings.theme.label")
                    description: I18n.t(root.uiLanguage, "settings.theme.desc")
                    defaultValue: "dms"
                    options: [
                        { label: I18n.t(root.uiLanguage, "settings.theme.dms"), value: "dms" },
                        { label: I18n.t(root.uiLanguage, "settings.theme.neon"), value: "neon" },
                        { label: I18n.t(root.uiLanguage, "settings.theme.umbrella"), value: "umbrella" },
                        { label: I18n.t(root.uiLanguage, "settings.theme.dark"), value: "dark" },
                        { label: I18n.t(root.uiLanguage, "settings.theme.light"), value: "light" }
                    ]
                }

                SavedSlider {
                    settingKey: "uiScale"
                    label: I18n.t(root.uiLanguage, "settings.scale.label")
                    description: I18n.t(root.uiLanguage, "settings.scale.desc")
                    defaultValue: 100
                    minimum: 80
                    maximum: 125
                    unit: "%"
                }

                ToggleSetting {
                    id: customToggle
                    settingKey: "themeCustomOn"
                    label: I18n.t(root.uiLanguage, "settings.customColors.label")
                    description: I18n.t(root.uiLanguage, "settings.customColors.desc")
                    defaultValue: false
                }

                Column {
                    width: parent.width
                    spacing: Theme.spacingM
                    visible: customToggle.value

                    ColorSetting { settingKey: "themeColor_accent"; label: I18n.t(root.uiLanguage, "settings.color.accent"); description: I18n.t(root.uiLanguage, "settings.color.accent.desc"); defaultValue: AgentTheme.primary.toString() }
                    ColorSetting { settingKey: "themeColor_panel"; label: I18n.t(root.uiLanguage, "settings.color.panel"); description: I18n.t(root.uiLanguage, "settings.color.panel.desc"); defaultValue: AgentTheme.surfaceContainer.toString() }
                    ColorSetting { settingKey: "themeColor_text"; label: I18n.t(root.uiLanguage, "settings.color.text"); defaultValue: AgentTheme.surfaceText.toString() }
                    ColorSetting { settingKey: "themeColor_outline"; label: I18n.t(root.uiLanguage, "settings.color.outline"); defaultValue: AgentTheme.outlineVariant.toString() }
                    ColorSetting { settingKey: "themeColor_neonFrom"; label: I18n.t(root.uiLanguage, "settings.color.neonFrom"); description: I18n.t(root.uiLanguage, "settings.color.neonFrom.desc"); defaultValue: AgentTheme.neon0.toString() }
                    ColorSetting { settingKey: "themeColor_neonTo"; label: I18n.t(root.uiLanguage, "settings.color.neonTo"); description: I18n.t(root.uiLanguage, "settings.color.neonTo.desc"); defaultValue: AgentTheme.neon3.toString() }
                }

                ToggleSetting {
                    id: advancedToggle
                    settingKey: "themeAdvancedOn"
                    label: I18n.t(root.uiLanguage, "settings.advanced.label")
                    description: I18n.t(root.uiLanguage, "settings.advanced.desc")
                    defaultValue: false
                }

                Column {
                    width: parent.width
                    spacing: Theme.spacingM
                    visible: advancedToggle.value

                    Repeater {
                        model: [
                            { key: "primary" },
                            { key: "primaryText" },
                            { key: "surface" },
                            { key: "surfaceContainer" },
                            { key: "surfaceContainerHighest" },
                            { key: "surfaceVariant" },
                            { key: "surfaceText" },
                            { key: "surfaceVariantText" },
                            { key: "outlineVariant" },
                            { key: "hoverTint" },
                            { key: "error" },
                            { key: "danger" },
                            { key: "warning" },
                            { key: "neon0" },
                            { key: "neon1" },
                            { key: "neon2" },
                            { key: "neon3" }
                        ]
                        delegate: ColorSetting {
                            required property var modelData
                            settingKey: "themeAdv_" + modelData.key
                            label: I18n.t(root.uiLanguage, "settings.role." + modelData.key)
                            defaultValue: AgentTheme[modelData.key].toString()
                        }
                    }
                }
            }
        }

        StyledRect {
            width: parent.width
            height: shellCol.implicitHeight + Theme.spacingL * 2
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHigh

            Column {
                id: shellCol
                x: Theme.spacingL
                y: Theme.spacingL
                width: parent.width - Theme.spacingL * 2
                spacing: Theme.spacingM

                StyledText {
                    text: I18n.t(root.uiLanguage, "settings.section.bar")
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                SavedSlider {
                    settingKey: "bubbleFontSize"
                    label: I18n.t(root.uiLanguage, "settings.textSize.label")
                    description: I18n.t(root.uiLanguage, "settings.textSize.desc")
                    defaultValue: 13
                    minimum: 11
                    maximum: 22
                    unit: "px"
                }

                SavedSlider {
                    settingKey: "panelHeightPercent"
                    label: I18n.t(root.uiLanguage, "settings.chatHeight.label")
                    description: I18n.t(root.uiLanguage, "settings.chatHeight.desc")
                    defaultValue: 75
                    minimum: 40
                    maximum: 95
                    unit: "%"
                }

                SavedSlider {
                    settingKey: "backgroundOpacity"
                    label: I18n.t(root.uiLanguage, "settings.transparency.label")
                    description: I18n.t(root.uiLanguage, "settings.transparency.desc")
                    defaultValue: 100
                    minimum: 30
                    maximum: 100
                    unit: "%"
                }

                ToggleSetting {
                    settingKey: "liquidGlass"
                    label: I18n.t(root.uiLanguage, "settings.glass.label")
                    description: I18n.t(root.uiLanguage, "settings.glass.desc")
                    defaultValue: false
                }

                ToggleSetting {
                    settingKey: "updateNotify"
                    label: I18n.t(root.uiLanguage, "settings.updateNotice.label")
                    description: I18n.t(root.uiLanguage, "settings.updateNotice.desc")
                    defaultValue: false
                }

                StringSetting {
                    settingKey: "pillLabel"
                    label: I18n.t(root.uiLanguage, "settings.pill.label")
                    description: I18n.t(root.uiLanguage, "settings.pill.desc")
                    placeholder: "Jarvis"
                    defaultValue: "Jarvis"
                }

                StringSetting {
                    settingKey: "hotkey"
                    label: I18n.t(root.uiLanguage, "settings.hotkey.label")
                    description: I18n.t(root.uiLanguage, "settings.hotkey.desc")
                    placeholder: I18n.t(root.uiLanguage, "settings.hotkey.placeholder")
                    defaultValue: ""
                }
            }
        }

        StyledRect {
            width: parent.width
            height: voiceCol.implicitHeight + Theme.spacingL * 2
            radius: Theme.cornerRadius
            color: Theme.surfaceContainerHigh

            Column {
                id: voiceCol
                x: Theme.spacingL
                y: Theme.spacingL
                width: parent.width - Theme.spacingL * 2
                spacing: Theme.spacingM

                StyledText {
                    text: I18n.t(root.uiLanguage, "settings.section.voice")
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                SavedSelection {
                    settingKey: "voiceModel"
                    label: I18n.t(root.uiLanguage, "settings.whisper.label")
                    description: I18n.t(root.uiLanguage, "settings.whisper.desc")
                    defaultValue: "auto"
                    options: [
                        { label: I18n.t(root.uiLanguage, "settings.whisper.auto"), value: "auto" },
                        { label: I18n.t(root.uiLanguage, "settings.whisper.gpu"), value: "large-v3-turbo" },
                        { label: I18n.t(root.uiLanguage, "settings.whisper.medium"), value: "medium" },
                        { label: I18n.t(root.uiLanguage, "settings.whisper.small"), value: "small" },
                        { label: I18n.t(root.uiLanguage, "settings.whisper.base"), value: "base" }
                    ]
                }

                StringSetting {
                    settingKey: "voiceLanguage"
                    label: I18n.t(root.uiLanguage, "settings.language.label")
                    description: I18n.t(root.uiLanguage, "settings.language.desc")
                    placeholder: "auto"
                    defaultValue: "auto"
                }

                SavedSelection {
                    settingKey: "voiceDevice"
                    label: I18n.t(root.uiLanguage, "settings.mic.label")
                    description: I18n.t(root.uiLanguage, "settings.mic.desc")
                    defaultValue: ""
                    options: micOptions
                }

                ToggleSetting {
                    settingKey: "voiceWarmup"
                    label: I18n.t(root.uiLanguage, "settings.warmup.label")
                    description: I18n.t(root.uiLanguage, "settings.warmup.desc")
                    defaultValue: false
                }

                StringSetting {
                    settingKey: "voiceVenv"
                    label: I18n.t(root.uiLanguage, "settings.venv.label")
                    description: I18n.t(root.uiLanguage, "settings.venv.desc")
                    placeholder: I18n.t(root.uiLanguage, "settings.venv.placeholder")
                    defaultValue: ""
                }
            }
        }
    }
}
