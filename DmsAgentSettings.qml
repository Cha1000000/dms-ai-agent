import QtQuick
import QtQuick.Layouts
import Quickshell.Services.Pipewire
import qs.Common
import qs.Widgets
import qs.Modules.Plugins

PluginSettings {
    id: root
    pluginId: "dmsAgent"

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
                    text: "Claude"
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

                SavedSelection {
                    settingKey: "permissionMode"
                    label: "Permissions"
                    description: "Ask first: the chat shows an Allow / Deny dialog before the agent runs a command or changes a file. No confirmation: the agent acts immediately (Claude Code runs with --dangerously-skip-permissions, unrestricted shell access as you)."
                    defaultValue: "confirm"
                    options: [
                        { label: "Ask first", value: "confirm" },
                        { label: "No confirmation", value: "auto" }
                    ]
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
                    description: "Jarvis is the signature look: your DMS colors with a neon gradient rim. DMS Colors is the same without the neon."
                    defaultValue: "jarvis"
                    options: [
                        { label: "Jarvis (neon)", value: "jarvis" },
                        { label: "DMS Colors", value: "dms" },
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
                            { key: "error", label: "Danger (recording, delete)" },
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
                    settingKey: "autoUpdate"
                    label: "Auto-update"
                    description: "Pull new versions from the plugin's repository once per boot and restart the shell to apply them. Local edits are never touched."
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
