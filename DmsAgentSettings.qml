import QtQuick
import QtQuick.Layouts
import Quickshell.Io
import Quickshell
import Quickshell.Services.Pipewire
import qs.Common
import qs.Widgets
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
    readonly property var providerOptions: {
        const list = [];
        for (const p of Providers.all())
            list.push({ label: p.title, value: p.id });
        return list;
    }

    // Ask-first needs the can_use_tool handshake; Qoder and CVC do not speak it,
    // so those providers only offer "No confirmation".
    readonly property bool providerCanAskFirst: {
        const p = Providers.byId(providerSelect.value || "claude");
        return !!(p.caps && p.caps.askFirst);
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
