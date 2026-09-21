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
                    description: "haiku (fast), sonnet (balanced), opus (best)"
                    placeholder: "haiku"
                    defaultValue: "haiku"
                }

                ToggleSetting {
                    settingKey: "extendedThinking"
                    label: "Extended Thinking"
                    description: "Deeper reasoning, slower responses. Best with sonnet/opus."
                    defaultValue: false
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
                    description: "Toggles the chat on the focused monitor, e.g. Mod+Space or Mod+Shift+A. Empty removes it. Written to ~/.config/niri/dms-ai-agent.kdl"
                    placeholder: "Mod+Space"
                    defaultValue: "Mod+Space"
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

                SelectionSetting {
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

                SelectionSetting {
                    settingKey: "voiceDevice"
                    label: "Microphone"
                    description: "Which microphone dictation records from. The stored value is the PipeWire node name, so it survives renaming the list."
                    defaultValue: ""
                    options: micOptions
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
