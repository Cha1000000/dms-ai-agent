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
    // own language means the plugin to speak it too.
    readonly property string uiLanguage: {
        var lang = Quickshell.env("LC_ALL") || Quickshell.env("LC_MESSAGES")
                    || Quickshell.env("LANG") || "";
        return String(lang).substring(0, 2).toLowerCase();
    }

    // Microphones offered in the dropdown. Sinks are outputs and streams are
    // individual apps, so both are filtered out; what is left are capture devices.
    // The label is what the audio settings show, the stored value is the node
    // name, which is what pw-record takes as --target.
    readonly property var micNodes: Pipewire.nodes.values.filter(n => n && n.audio && !n.isSink && !n.isStream)

    readonly property var micOptions: {
        const list = [{ label: "System default", value: "" }];
        for (const node of micNodes)
            list.push({ label: micLabel(node), value: node.name });
        return list;
    }

    // Agent CLIs the chat can run. Providers.js is the registry; adding one there
    // is enough for it to show up here and in the model picker.
    property var externalProviders: ({})
    readonly property var providerOptions: {
        const list = [];
        for (const p of Providers.all())
            list.push({ label: p.title, value: p.id });
        for (const id of Object.keys(externalProviders)) {
            const p = externalProviders[id];
            if (p && ["acp", "codex", "openai"].indexOf(p.adapter) >= 0)
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
                { label: "Ask first", value: "confirm" },
                { label: "No confirmation", value: "auto" }
            ];
        return [{ label: "No confirmation (ask first unavailable for this provider)", value: "auto" }];
    }
    readonly property string permissionModeDesc: {
        if (providerCanAskFirst)
            return "Ask first: the chat shows an Allow / Deny dialog before the agent runs a command or changes a file. No confirmation: the agent acts immediately (Claude Code runs with --dangerously-skip-permissions, unrestricted shell access as you).";
        return "This provider cannot pause for permission prompts, so the chat always runs unattended (equivalent to --dangerously-skip-permissions).";
    }

    // A provider without the permission handshake cannot honour "confirm"; the
    // stored value follows the provider so the picker never claims a dialog that
    // will not appear. Checked on open too — the handler alone only sees a change.
    function syncPermissionMode() {
        if (!providerCanAskFirst)
            saveValue("permissionMode", "auto");
    }
    onProviderCanAskFirstChanged: syncPermissionMode()
    Component.onCompleted: Qt.callLater(syncPermissionMode)

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
                    cvcKey.keyResult = String(text).trim() === "ok" ? "Saved" : "Failed to save";
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
                        cvcKey.keyResult = "Key works — " + out.substring(3) + " models";
                    else if (out === "missing")
                        cvcKey.keyResult = "No key saved yet";
                    else
                        cvcKey.keyResult = out;
                }
            }
        }
        property string keyResult: ""

        StyledText {
            text: "CheapVibeCode API key"
            font.pixelSize: Theme.fontSizeMedium
            font.weight: Font.Medium
            color: Theme.surfaceText
        }
        StyledText {
            text: "Stored only on this machine in ~/.local/state/dms-agent/providers.json (0600), never in synced plugin settings. Get a key at cheapvibecode.ru."
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
                placeholderText: cvcKey.keyStatus === "set" ? "key saved — type to replace" : "sk-cvc-..."
                showPasswordToggle: true
                echoMode: TextInput.Password
            }
            DankButton {
                id: saveBtn
                text: "Save"
                onClicked: {
                    if (keyField.text.trim() === "") return;
                    keySave.pendingKey = keyField.text.trim();
                    keyField.text = "";
                    keySave.running = true;
                }
            }
            DankButton {
                id: testBtn
                text: "Test"
                onClicked: {
                    cvcKey.keyResult = "Checking…";
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
        width: parent.width
        spacing: Theme.spacingM

        property var providers: ({})
        property bool loadFailed: false
        property string loadError: ""
        property bool registryLoaded: false
        property string editorId: ""
        property bool jsonMode: false
        property string formError: ""
        property var pendingEntry: null
        property string pendingId: ""
        property string pendingKey: ""
        property string pendingCommandText: ""
        property string pendingUrlValue: ""
        property bool pendingNeedsUrl: false

        function reload() {
            if (listProc.running) return;
            registryLoaded = false;
            listProc.command = ["python3", root.registryScript, "list", "--json"];
            listProc.running = true;
        }
        Component.onCompleted: Qt.callLater(reload)

        Process {
            id: listProc
            stdout: StdioCollector {
                onStreamFinished: {
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
                        regProviders.loadError = String(text).trim() || String(e);
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
                if (regProviders.editorId === removeProc.pendingId) regProviders.startNew();
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

        function startEdit(pid) {
            jsonMode = false;
            const e = providers[pid] || {};
            formId = pid;
            pendingEditId = pid;
            formAdapter = e.adapter || "acp";
            formTitle = e.title || "";
            formCommand = Array.isArray(e.command) ? e.command.join(" ") : String(e.command || "");
            formBaseUrl = e.baseUrl || "";
            formError = "";
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
        }
        function validateEntry(pid, entry) {
            if (!/^[a-z0-9-]+$/.test(pid)) return "settings.reg.badId";
            if (!entry || typeof entry !== "object" || Array.isArray(entry)) return "settings.reg.badEntry";
            if (Object.keys(entry).some(k => ["adapter", "title", "command", "baseUrl"].indexOf(k) < 0))
                return "settings.reg.badFields";
            if (["acp", "codex", "openai"].indexOf(entry.adapter) < 0) return "settings.reg.badAdapter";
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
                formError = I18n.t(root.uiLanguage, error);
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
                formError = I18n.t(root.uiLanguage, "settings.reg.idConflict");
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
                text: I18n.t(root.uiLanguage, "settings.reg.add")
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
                            }
                            StyledText {
                                text: regRow.entry.adapter || ""
                                font.pixelSize: Theme.fontSizeSmall
                                color: Theme.surfaceVariantText
                            }
                            Rectangle {
                                width: editRow.width + Theme.spacingS; height: Theme.iconSize
                                radius: Theme.cornerRadius
                                color: editArea.containsMouse ? Theme.withAlpha(Theme.primary, 0.2) : "transparent"
                                Row {
                                    id: editRow
                                    anchors.centerIn: parent
                                    spacing: Theme.spacingXXS
                                    DankIcon { name: "edit"; size: Theme.iconSizeSmall; color: editArea.containsMouse ? Theme.primary : Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                                    StyledText { text: I18n.t(root.uiLanguage, "settings.reg.edit"); font.pixelSize: Theme.fontSizeSmall; color: editArea.containsMouse ? Theme.primary : Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                                }
                                MouseArea {
                                    id: editArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: regProviders.startEdit(modelData)
                                }
                            }
                            DankButton {
                                text: I18n.t(root.uiLanguage, "settings.reg.jsonEdit")
                                onClicked: regProviders.openJson(modelData)
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
                                        regProviders.confirmRemoveDialog.visible = true;
                                    }
                                }
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
            anchors.fill: parent
            color: Theme.withAlpha(Theme.shadow, 0.55)
            z: 30
            MouseArea { anchors.fill: parent; onClicked: confirmRemoveDialog.visible = false }
            Rectangle {
                width: parent.width - Theme.spacingXL * 2
                height: rmCol.height + Theme.spacingL * 2
                anchors.centerIn: parent
                radius: Theme.cornerRadius
                color: Theme.surfaceContainerHighest
                MouseArea { anchors.fill: parent }
                Column {
                    id: rmCol
                    anchors.centerIn: parent
                    width: parent.width - Theme.spacingL * 2
                    spacing: Theme.spacingM
                    StyledText {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: I18n.t(root.uiLanguage, "settings.reg.confirmRemove") + "\n" + regProviders.confirmRemoveId + " (" + regProviders.confirmRemoveTitle + ")"
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.surfaceText
                    }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
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

        // Command-change confirmation: the new argv will be executed as-is.
        Rectangle {
            id: confirmCommandDialog
            visible: false
            anchors.fill: parent
            color: Theme.withAlpha(Theme.shadow, 0.55)
            z: 30
            MouseArea { anchors.fill: parent; onClicked: confirmCommandDialog.visible = false }
            Rectangle {
                width: parent.width - Theme.spacingXL * 2
                height: cmdCol.height + Theme.spacingL * 2
                anchors.centerIn: parent
                radius: Theme.cornerRadius
                color: Theme.surfaceContainerHighest
                MouseArea { anchors.fill: parent }
                Column {
                    id: cmdCol
                    anchors.centerIn: parent
                    width: parent.width - Theme.spacingL * 2
                    spacing: Theme.spacingM
                    StyledText {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: I18n.t(root.uiLanguage, "settings.reg.confirmCommand") + "\n" + regProviders.pendingCommandText
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.surfaceText
                    }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
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
        }

        // URL-change confirmation: the stored API key would be sent to a new origin.
        Rectangle {
            id: confirmUrlDialog
            visible: false
            anchors.fill: parent
            color: Theme.withAlpha(Theme.shadow, 0.55)
            z: 30
            MouseArea { anchors.fill: parent; onClicked: confirmUrlDialog.visible = false }
            Rectangle {
                width: parent.width - Theme.spacingXL * 2
                height: urlCol.height + Theme.spacingL * 2
                anchors.centerIn: parent
                radius: Theme.cornerRadius
                color: Theme.surfaceContainerHighest
                MouseArea { anchors.fill: parent }
                Column {
                    id: urlCol
                    anchors.centerIn: parent
                    width: parent.width - Theme.spacingL * 2
                    spacing: Theme.spacingM
                    StyledText {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: I18n.t(root.uiLanguage, "settings.reg.confirmUrl") + "\n" + regProviders.pendingUrlValue
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.surfaceText
                    }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
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
        }

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
                    onClicked: regProviders.startNew()
                }
            }
        }

        // --- The form ---
        Column {
            width: parent.width
            spacing: Theme.spacingS
            visible: !regProviders.jsonMode

            StyledText {
                text: regProviders.formId === ""
                      ? I18n.t(root.uiLanguage, "settings.reg.newProvider")
                      : I18n.t(root.uiLanguage, "settings.reg.editing") + " " + regProviders.formId
                font.pixelSize: Theme.fontSizeSmall
                font.weight: Font.Medium
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
                    onTextEdited: regProviders.formId = text
                }
                DDropdown {
                    id: formAdapterSelect
                    width: 160
                    text: ""
                    currentValue: regProviders.formAdapter === "acp" ? "ACP"
                                  : regProviders.formAdapter === "codex" ? "Codex" : "OpenAI gateway"
                    options: ["ACP", "Codex", "OpenAI gateway"]
                    onValueChanged: newValue => {
                        regProviders.formAdapter = newValue === "ACP" ? "acp"
                            : newValue === "Codex" ? "codex" : "openai";
                    }
                }
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
                onTextEdited: regProviders.formCommand = text
            }

            DankTextField {
                id: formUrlField
                width: parent.width
                visible: regProviders.formAdapter === "openai"
                placeholderText: I18n.t(root.uiLanguage, "settings.reg.urlPlaceholder")
                text: regProviders.formBaseUrl
                onTextEdited: regProviders.formBaseUrl = text
            }

            DankTextField {
                id: formKeyField
                width: parent.width
                placeholderText: I18n.t(root.uiLanguage, "settings.reg.keyPlaceholder")
                showPasswordToggle: true
                echoMode: TextInput.Password
            }

            StyledText {
                visible: regProviders.formError !== ""
                width: parent.width
                wrapMode: Text.WordWrap
                text: regProviders.formError
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.withAlpha(Theme.error, 0.9)
            }

            Row {
                spacing: Theme.spacingS
                DankButton {
                    text: regProviders.pendingEditId === "" ? I18n.t(root.uiLanguage, "settings.reg.add") : I18n.t(root.uiLanguage, "settings.reg.save")
                    enabled: regProviders.registryLoaded && !regProviders.loadFailed && !saveProc.running && !keyProc.running
                    onClicked: regProviders.submit()
                }
                DankButton {
                    visible: regProviders.formId !== ""
                    text: I18n.t(root.uiLanguage, "settings.reg.cancel")
                    onClicked: regProviders.startNew()
                }
            }

            StyledText {
                width: parent.width
                wrapMode: Text.WordWrap
                text: I18n.t(root.uiLanguage, "settings.reg.hint")
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceVariantText
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
            return I18n.t(root.uiLanguage, "loginHint." + provider);
        }
        property string state: ""      // "set" | "missing" | ""

        onProviderIdChanged: refresh()
        Component.onCompleted: Qt.callLater(refresh)

        // The command is built here, not bound: a binding on `providerId` is
        // re-evaluated after this change handler, so the first check after a
        // provider switch would still run against the previous provider.
        function refresh() {
            check.command = ["python3", secretsScript, "check", providerId];
            check.running = true;
        }

        Process {
            id: check
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
            text: "Not signed in. " + signIn.hint(signIn.providerId)
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
            text: "DMS AI Agent Settings"
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
                    text: "Provider"
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                RegistryProviders {
                    id: registryProviders
                }

                SavedSelection {
                    id: providerSelect
                    settingKey: "provider"
                    label: "Agent"
                    description: "Which agent CLI runs the chat. Claude Code is the default and works with the subscription you are signed in to. Other providers sign in on their own (an OAuth login or an API key) — see their status below once they are set up."
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
                    text: "Model & Effort"
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                StringSetting {
                    settingKey: "claudeModel"
                    label: "Model"
                    description: "haiku / sonnet / opus or a full id, e.g. claude-opus-5-5"
                    placeholder: "haiku"
                    defaultValue: "haiku"
                }

                StringSetting {
                    settingKey: "effort"
                    label: "Effort"
                    description: "low, medium, high, xhigh or max; empty = auto. Only for models that support it."
                    placeholder: "auto"
                    defaultValue: ""
                }

                ToggleSetting {
                    settingKey: "restoreSessionModel"
                    label: "Per-session model"
                    description: "Opening a chat from the history also switches to the model and effort it was last used with."
                    defaultValue: true
                }

                StringSetting {
                    settingKey: "workDir"
                    label: "Working directory"
                    description: "Where the agent starts, as if you ran claude in a terminal there: it picks up that folder's CLAUDE.md and project settings and can work on its files. Applied as soon as you press Enter or leave the field: the chat switches to a new conversation with that folder's own history, and a folder chip with its name appears in the chat. Empty = a private folder (~/.local/state/dms-agent). Accepts ~/path or an absolute path."
                    placeholder: "~/projects/my-app"
                    defaultValue: ""
                }

                SavedSelection {
                    id: permissionSelect
                    settingKey: "permissionMode"
                    label: "Permissions"
                    description: permissionModeDesc
                    defaultValue: "confirm"
                    options: permissionModeOptions
                }

                StringSetting {
                    settingKey: "maxTokens"
                    label: "Max Tokens"
                    description: "Maximum response length"
                    placeholder: "1024"
                    defaultValue: "1024"
                }

                StyledText {
                    text: "System Prompt"
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                    topPadding: Theme.spacingS
                }

                StringSetting {
                    settingKey: "systemPrompt"
                    label: "System Prompt"
                    description: "Custom instructions (leave empty for default)"
                    placeholder: "You are a helpful desktop assistant..."
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
                    text: "Theme & Size"
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                SavedSelection {
                    settingKey: "themePreset"
                    label: "Theme"
                    description: "DMS Colors follows your DMS theme. Neon keeps the DMS surfaces but uses a blue neon accent and a gradient rim."
                    defaultValue: "dms"
                    options: [
                        { label: "DMS Colors", value: "dms" },
                        { label: "Neon", value: "neon" },
                        { label: "Umbrella (red neon)", value: "umbrella" },
                        { label: "Dark neutral", value: "dark" },
                        { label: "Light", value: "light" }
                    ]
                }

                SavedSlider {
                    settingKey: "uiScale"
                    label: "Window Scale"
                    description: "Zooms the whole chat window: text, buttons, corners and spacing. Message Text Size is applied on top of it."
                    defaultValue: 100
                    minimum: 80
                    maximum: 125
                    unit: "%"
                }

                ToggleSetting {
                    id: customToggle
                    settingKey: "themeCustomOn"
                    label: "Custom colors"
                    description: "Override the key colors of the chosen theme."
                    defaultValue: false
                }

                Column {
                    width: parent.width
                    spacing: Theme.spacingM
                    visible: customToggle.value

                    ColorSetting { settingKey: "themeColor_accent"; label: "Accent"; description: "Buttons, your messages, selection."; defaultValue: AgentTheme.primary.toString() }
                    ColorSetting { settingKey: "themeColor_panel"; label: "Panel & bubbles"; description: "Background of the input card, assistant bubbles and menus."; defaultValue: AgentTheme.surfaceContainer.toString() }
                    ColorSetting { settingKey: "themeColor_text"; label: "Text"; defaultValue: AgentTheme.surfaceText.toString() }
                    ColorSetting { settingKey: "themeColor_outline"; label: "Borders"; defaultValue: AgentTheme.outlineVariant.toString() }
                    ColorSetting { settingKey: "themeColor_neonFrom"; label: "Neon: start"; description: "Left end of the gradient rim (themes with neon)."; defaultValue: AgentTheme.neon0.toString() }
                    ColorSetting { settingKey: "themeColor_neonTo"; label: "Neon: end"; description: "Right end of the gradient rim."; defaultValue: AgentTheme.neon3.toString() }
                }

                ToggleSetting {
                    id: advancedToggle
                    settingKey: "themeAdvancedOn"
                    label: "Advanced: edit every color"
                    description: "For fine tuning. Each color below replaces one role of the theme; it wins over the key colors above."
                    defaultValue: false
                }

                Column {
                    width: parent.width
                    spacing: Theme.spacingM
                    visible: advancedToggle.value

                    Repeater {
                        model: [
                            { key: "primary", label: "Primary (accent, user bubble)" },
                            { key: "primaryText", label: "Text on primary" },
                            { key: "surface", label: "Tool step background" },
                            { key: "surfaceContainer", label: "Assistant bubble, input card" },
                            { key: "surfaceContainerHighest", label: "Menus and dialogs" },
                            { key: "surfaceVariant", label: "Hover and secondary fills" },
                            { key: "surfaceText", label: "Text" },
                            { key: "surfaceVariantText", label: "Muted text and icons" },
                            { key: "outlineVariant", label: "Borders" },
                            { key: "hoverTint", label: "Hover highlight" },
                            { key: "error", label: "Error (recording, error messages)" },
                            { key: "danger", label: "Delete buttons and delete hovers" },
                            { key: "warning", label: "Warning (tool steps)" },
                            { key: "neon0", label: "Neon 1" },
                            { key: "neon1", label: "Neon 2" },
                            { key: "neon2", label: "Neon 3" },
                            { key: "neon3", label: "Neon 4" }
                        ]
                        delegate: ColorSetting {
                            required property var modelData
                            settingKey: "themeAdv_" + modelData.key
                            label: modelData.label
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
                    text: "Bar & Hotkey"
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                SavedSlider {
                    settingKey: "bubbleFontSize"
                    label: "Message Text Size"
                    description: "Font size in the chat bubbles. Larger is easier to read at a glance."
                    defaultValue: 13
                    minimum: 11
                    maximum: 22
                    unit: "px"
                }

                SavedSlider {
                    settingKey: "panelHeightPercent"
                    label: "Chat Height"
                    description: "How much of the monitor's height the chat window takes."
                    defaultValue: 75
                    minimum: 40
                    maximum: 95
                    unit: "%"
                }

                SavedSlider {
                    settingKey: "backgroundOpacity"
                    label: "Background Transparency"
                    description: "Transparency of the chat window and message bubbles. Lower is more transparent; with Liquid Glass on it sets how dense the glass tint is."
                    defaultValue: 100
                    minimum: 30
                    maximum: 100
                    unit: "%"
                }

                ToggleSetting {
                    settingKey: "liquidGlass"
                    label: "Liquid Glass"
                    description: "Translucent glass bubbles with a highlighted edge and the background blurred behind each one. Needs Blur enabled in DMS; without it, and in the Light theme, the bubbles stay solid."
                    defaultValue: false
                }

                ToggleSetting {
                    settingKey: "updateNotify"
                    label: "Update notice"
                    description: "Once per boot, check the plugin's repository and show a notification when a newer version exists. Nothing is installed; update in Settings → Plugins."
                    defaultValue: false
                }

                StringSetting {
                    settingKey: "pillLabel"
                    label: "Pill Label"
                    description: "Text next to the icon in the bar"
                    placeholder: "Jarvis"
                    defaultValue: "Jarvis"
                }

                StringSetting {
                    settingKey: "hotkey"
                    label: "Chat Hotkey (niri)"
                    description: "Toggles the chat on the focused monitor, e.g. Mod+Space or Mod+Shift+A. No hotkey by default; empty removes it. A set hotkey overrides an existing bind on the same key. Written to ~/.config/niri/dms-ai-agent.kdl"
                    placeholder: "none; e.g. Mod+Space"
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
                    text: "Voice Input"
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                SavedSelection {
                    settingKey: "voiceModel"
                    label: "Whisper Model"
                    description: "Auto: large-v3-turbo with an NVIDIA GPU, small on CPU. Downloaded on first use."
                    defaultValue: "auto"
                    options: [
                        { label: "Auto", value: "auto" },
                        { label: "large-v3-turbo (GPU)", value: "large-v3-turbo" },
                        { label: "medium", value: "medium" },
                        { label: "small", value: "small" },
                        { label: "base (fastest)", value: "base" }
                    ]
                }

                StringSetting {
                    settingKey: "voiceLanguage"
                    label: "Language"
                    description: "auto, or a code such as en, ru, de. A fixed language is more accurate for short phrases."
                    placeholder: "auto"
                    defaultValue: "auto"
                }

                SavedSelection {
                    settingKey: "voiceDevice"
                    label: "Microphone"
                    description: "Which microphone dictation records from. The stored value is the PipeWire node name, so it survives renaming the list."
                    defaultValue: ""
                    options: micOptions
                }

                ToggleSetting {
                    settingKey: "voiceWarmup"
                    label: "Warm up on open"
                    description: "Load the speech model whenever the chat opens (about 900 MB of memory while it is open), so the first dictation is not clipped. Leave off if you do not dictate."
                    defaultValue: false
                }

                StringSetting {
                    settingKey: "voiceVenv"
                    label: "Whisper venv"
                    description: "Python venv with faster-whisper (install.sh creates the default one)"
                    placeholder: "~/.local/share/dms-ai-agent/whisper-venv"
                    defaultValue: ""
                }
            }
        }
    }
}
