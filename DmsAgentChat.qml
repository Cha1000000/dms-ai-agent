import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import qs.Common
import qs.Widgets
import "markdown2html.js" as Md

Item {
    id: chatRoot

    signal escapePressed()

    // --- Input Card (anchored to bottom) ---
    Rectangle {
        id: inputCard
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: inputCol.height
        radius: 20; color: Theme.surfaceContainer
        border.width: 1; border.color: Theme.outlineVariant
        z: 10

        layer.enabled: true
        layer.effect: MultiEffect {
            shadowEnabled: true; shadowBlur: 0.8
            shadowVerticalOffset: -2; shadowColor: Theme.withAlpha(Theme.shadow || "#000000", 0.4)
        }

        ColumnLayout {
            id: inputCol; width: parent.width; spacing: 0

            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(44, inputField.contentHeight + 24)

                TextEdit {
                    id: inputField
                    anchors.fill: parent
                    anchors.leftMargin: 18; anchors.rightMargin: 18
                    anchors.topMargin: 12; anchors.bottomMargin: 12
                    color: Theme.surfaceText; font.pixelSize: 14
                    wrapMode: TextEdit.Wrap; clip: true

                    Text {
                        visible: !inputField.text && !inputField.activeFocus
                        text: "Message..."
                        color: Theme.surfaceVariantText; font.pixelSize: 14
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Keys.onReturnPressed: function(event) {
                        if (event.modifiers & Qt.ShiftModifier) event.accepted = false;
                        else { event.accepted = true; sendCurrentMessage(); }
                    }

                    Keys.onEscapePressed: function(event) {
                        event.accepted = true; chatRoot.escapePressed();
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true; Layout.leftMargin: 14; Layout.rightMargin: 14
                height: 1; color: Theme.withAlpha(Theme.outlineVariant, 0.3)
            }

            Item {
                Layout.fillWidth: true; Layout.preferredHeight: 40

                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8; spacing: 4

                    // Model dropdown
                    Rectangle {
                        width: modelRow.implicitWidth + 16; height: 26; radius: 13
                        color: modelDropArea.containsMouse || modelDropdown.visible ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent"

                        Row {
                            id: modelRow; anchors.centerIn: parent; spacing: 4
                            Text { text: AgentService.claudeModel; font.pixelSize: 11; color: Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                            DankIcon { name: modelDropdown.visible ? "expand_less" : "expand_more"; color: Theme.surfaceVariantText; size: 14; anchors.verticalCenter: parent.verticalCenter }
                        }

                        MouseArea { id: modelDropArea; anchors.fill: parent; hoverEnabled: true; onClicked: modelDropdown.visible = !modelDropdown.visible }
                    }

                    // Think
                    Rectangle {
                        width: thinkRow.implicitWidth + 14; height: 26; radius: 13
                        color: AgentService.extendedThinking ? Theme.withAlpha(Theme.primary, 0.15) : (thinkArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent")
                        Row {
                            id: thinkRow; anchors.centerIn: parent; spacing: 4
                            DankIcon { name: "psychology"; color: AgentService.extendedThinking ? Theme.primary : Theme.surfaceVariantText; size: 14; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: "Think"; font.pixelSize: 11; color: AgentService.extendedThinking ? Theme.primary : Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                        }
                        MouseArea { id: thinkArea; anchors.fill: parent; hoverEnabled: true; onClicked: AgentService.extendedThinking = !AgentService.extendedThinking }
                    }

                    // New chat
                    Rectangle {
                        width: 26; height: 26; radius: 13
                        color: newChatArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent"
                        DankIcon { anchors.centerIn: parent; name: "add"; color: Theme.surfaceVariantText; size: 16 }
                        MouseArea { id: newChatArea; anchors.fill: parent; hoverEnabled: true; onClicked: { AgentService.clearMessages(); messageModel.clear(); } }
                    }

                    // History
                    Rectangle {
                        width: 26; height: 26; radius: 13
                        color: historyArea.containsMouse || historyDropdown.visible ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent"
                        DankIcon { anchors.centerIn: parent; name: "history"; color: Theme.surfaceVariantText; size: 16 }
                        MouseArea { id: historyArea; anchors.fill: parent; hoverEnabled: true; onClicked: { AgentService.loadHistory(); historyDropdown.visible = !historyDropdown.visible; } }
                    }

                    Item { Layout.fillWidth: true }

                    // Cost
                    Text {
                        visible: AgentService.lastCost !== ""; text: AgentService.lastCost
                        font.pixelSize: 9; color: Theme.withAlpha(Theme.surfaceVariantText, 0.5)
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    // Send / Status
                    Row {
                        spacing: 6
                        anchors.verticalCenter: parent.verticalCenter
                        visible: AgentService.busy

                        Rectangle {
                            width: 6; height: 6; radius: 3
                            anchors.verticalCenter: parent.verticalCenter; color: Theme.primary
                            SequentialAnimation on opacity {
                                running: AgentService.busy; loops: Animation.Infinite
                                NumberAnimation { to: 0.2; duration: 600; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutSine }
                            }
                        }

                        Text {
                            text: AgentService.statusText
                            color: Theme.surfaceVariantText; font.pixelSize: 11
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Rectangle {
                            width: 22; height: 22; radius: 11
                            anchors.verticalCenter: parent.verticalCenter
                            color: cancelArea.containsMouse ? Theme.withAlpha(Theme.error || "#EF4444", 0.15) : "transparent"
                            DankIcon { anchors.centerIn: parent; name: "close"; color: Theme.surfaceVariantText; size: 14 }
                            MouseArea { id: cancelArea; anchors.fill: parent; hoverEnabled: true; onClicked: AgentService.cancelRequest() }
                        }
                    }

                    Rectangle {
                        visible: !AgentService.busy
                        width: 32; height: 32; radius: 16
                        color: canSend ? Theme.primary : Theme.withAlpha(Theme.surfaceVariant, 0.2)
                        property bool canSend: inputField.text.trim().length > 0
                        DankIcon { anchors.centerIn: parent; name: "arrow_upward"; color: parent.canSend ? Theme.primaryText : Theme.surfaceVariantText; size: 18 }
                        MouseArea { anchors.fill: parent; onClicked: if (parent.canSend) sendCurrentMessage() }
                    }
                }
            }
        }
    }

    // --- Model Dropdown (outside input card, z on top) ---
    Rectangle {
        id: modelDropdown; visible: false
        anchors.bottom: inputCard.top; anchors.bottomMargin: 6
        anchors.left: inputCard.left; anchors.leftMargin: 8
        width: 130; height: modelCol.height + 8; radius: 12
        color: Theme.surfaceContainerHighest; border.width: 1; border.color: Theme.outlineVariant
        z: 20

        Column {
            id: modelCol; anchors.top: parent.top; anchors.topMargin: 4
            anchors.left: parent.left; anchors.right: parent.right
            Repeater {
                model: [{ id: "haiku", label: "Haiku", desc: "Fast" }, { id: "sonnet", label: "Sonnet", desc: "Balanced" }, { id: "opus", label: "Opus", desc: "Best" }]
                Rectangle {
                    width: modelCol.width; height: 32; radius: 8
                    color: optArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent"
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 6
                        Text { text: modelData.label; font.pixelSize: 12; font.weight: AgentService.claudeModel === modelData.id ? Font.Bold : Font.Normal; color: AgentService.claudeModel === modelData.id ? Theme.surfaceText : Theme.surfaceVariantText }
                        Text { text: modelData.desc; font.pixelSize: 10; color: Theme.withAlpha(Theme.surfaceVariantText, 0.5) }
                        Item { Layout.fillWidth: true }
                        DankIcon { visible: AgentService.claudeModel === modelData.id; name: "check"; color: Theme.primary; size: 14 }
                    }
                    MouseArea { id: optArea; anchors.fill: parent; hoverEnabled: true; onClicked: { AgentService.claudeModel = modelData.id; modelDropdown.visible = false; } }
                }
            }
        }
    }

    // --- History Dropdown (outside input card, z on top) ---
    Rectangle {
        id: historyDropdown; visible: false
        anchors.bottom: inputCard.top; anchors.bottomMargin: 6
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: parent.top; anchors.topMargin: 8
        radius: 12; clip: true
        color: Theme.surfaceContainerHighest; border.width: 1; border.color: Theme.outlineVariant
        z: 20

        Text {
            visible: AgentService.history.length === 0
            text: "No conversations yet"; color: Theme.surfaceVariantText; font.pixelSize: 12
            anchors.centerIn: parent
        }

        ListView {
            anchors.fill: parent; anchors.margins: 4; clip: true; spacing: 0
            visible: AgentService.history.length > 0
            model: AgentService.history
            delegate: Rectangle {
                width: ListView.view.width; height: 36; radius: 8
                color: hArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent"
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 8
                    Text { text: modelData.title || "Chat"; font.pixelSize: 12; color: Theme.surfaceText; elide: Text.ElideRight; Layout.fillWidth: true }
                    Text {
                        text: { var d = new Date(modelData.date); return d.toLocaleDateString(undefined, {month:"short", day:"numeric"}) }
                        font.pixelSize: 10; color: Theme.surfaceVariantText
                    }
                }
                MouseArea { id: hArea; anchors.fill: parent; hoverEnabled: true; onClicked: { messageModel.clear(); AgentService.resumeSession(modelData.id); historyDropdown.visible = false; } }
            }
        }
    }


    // --- Messages container (fills space above input) ---
    Flickable {
        id: messageFlick
        anchors.top: parent.top
        anchors.bottom: inputCard.top
        anchors.bottomMargin: 12
        anchors.left: parent.left; anchors.right: parent.right
        anchors.leftMargin: 8; anchors.rightMargin: 8
        clip: true
        contentHeight: messageColumn.height
        contentWidth: width

        // Auto-scroll to bottom
        function scrollToEnd() {
            if (contentHeight > height)
                contentY = contentHeight - height;
        }

        Column {
            id: messageColumn
            width: parent.width
            spacing: 6

            // Spacer pushes messages to bottom
            Item {
                width: 1
                height: Math.max(0, messageFlick.height - messagesContent.height)
            }

            // Actual messages
            Column {
                id: messagesContent
                width: parent.width
                spacing: 6

                Repeater {
                    model: ListModel { id: messageModel }

                    Loader {
                        width: messagesContent.width
                        sourceComponent: {
                            if (model.msgRole === "tool_status") return toolComp;
                            if (model.msgRole === "user") return userComp;
                            if (model.msgRole === "assistant") return assistantComp;
                            return null;
                        }
                        property string content: model.msgContent || ""
                    }
                }
            }
        }

        onContentHeightChanged: { Qt.callLater(scrollToEnd); }
    }

    // --- Bubbles (no shadows to avoid clipping artifacts) ---
    Component {
        id: toolComp
        Item {
            height: toolBubble.height
            Rectangle {
                id: toolBubble; anchors.left: parent.left
                width: Math.min(parent.width * 0.85, toolIcon.width + toolText.implicitWidth + 30)
                height: 28; radius: 14
                color: Theme.surface; border.width: 1; border.color: Theme.outlineVariant

                DankIcon {
                    id: toolIcon; name: "build"; color: "#FF9800"; size: 13
                    anchors.left: parent.left; anchors.leftMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    id: toolText; text: content; color: Theme.surfaceVariantText
                    font.pixelSize: 11; font.family: "monospace"
                    elide: Text.ElideRight
                    anchors.left: toolIcon.right; anchors.leftMargin: 6
                    anchors.right: parent.right; anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    Component {
        id: userComp
        Item {
            height: uRect.height
            Rectangle {
                id: uRect; anchors.right: parent.right
                width: Math.min(parent.width * 0.8, uTxt.implicitWidth + 28)
                height: uTxt.implicitHeight + 20; radius: 16; color: Theme.primary
                Text { id: uTxt; anchors.fill: parent; anchors.margins: 10; anchors.leftMargin: 14; anchors.rightMargin: 14; text: content; wrapMode: Text.Wrap; color: Theme.primaryText; font.pixelSize: 13; lineHeight: 1.3 }
            }
        }
    }

    Component {
        id: assistantComp
        Item {
            height: aRect.height
            Rectangle {
                id: aRect; anchors.left: parent.left
                width: Math.min(parent.width * 0.85, aTxt.implicitWidth + 28)
                height: aTxt.implicitHeight + 20; radius: 16; color: Theme.surfaceContainer
                Text { id: aTxt; anchors.fill: parent; anchors.margins: 10; anchors.leftMargin: 14; anchors.rightMargin: 14; text: Md.markdownToHtml(content); textFormat: Text.RichText; wrapMode: Text.Wrap; color: Theme.surfaceText; font.pixelSize: 13; lineHeight: 1.4 }
            }
        }
    }

    function sendCurrentMessage() {
        var text = inputField.text.trim();
        if (!text || AgentService.busy) return;
        inputField.text = "";
        AgentService.sendMessage(text);
    }

    function loadMessages() {
        var msgs = AgentService.messages;
        for (var i = 0; i < msgs.length; i++) {
            var m = msgs[i];
            if (m.role === "tool" || m.role === "tool_result") continue;
            messageModel.append({ msgRole: m.role, msgContent: m.content || "", msgTimestamp: m.timestamp || 0 });
        }
    }

    function reloadMessages() {
        messageModel.clear();
        loadMessages();
        inputField.forceActiveFocus();
    }

    Component.onCompleted: { loadMessages(); inputField.forceActiveFocus(); }

    Connections {
        target: AgentService

        function onMessageAdded(message) {
            if (message.role === "tool" || message.role === "tool_result") return;
            messageModel.append({ msgRole: message.role, msgContent: message.content, msgTimestamp: message.timestamp });
        }
    }
}
