import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import Quickshell
import qs.Common
import qs.Widgets
import "markdown2html.js" as Md

Item {
    id: chatRoot

    signal escapePressed()

    // Copying a bubble takes the focus away from the input field, so it is handed
    // straight back — otherwise typing silently goes nowhere after a copy.
    function copyToClipboard(text) {
        if (!text) return;
        Quickshell.clipboardText = text;
        inputField.forceActiveFocus();
    }

    // Small chip shown in the corner of a bubble on hover.
    component CopyChip: Rectangle {
        id: chip

        property string label: ""
        property color fg: Theme.surfaceVariantText
        property color bg: Theme.surfaceVariant
        property color copiedColor: Theme.primary
        property bool copied: false

        signal requested()

        width: chipRow.width + 12
        height: 18
        radius: 9
        color: chipArea.containsMouse ? Theme.withAlpha(chip.bg, 1.0) : Theme.withAlpha(chip.bg, 0.85)
        border.width: 1
        border.color: Theme.withAlpha(chip.fg, 0.25)

        Timer { id: chipTimer; interval: 1200; onTriggered: chip.copied = false }

        Row {
            id: chipRow
            anchors.centerIn: parent
            spacing: 3

            DankIcon {
                name: chip.copied ? "check" : "content_copy"
                size: 11
                color: chip.copied ? chip.copiedColor : chip.fg
                anchors.verticalCenter: parent.verticalCenter
            }

            Text {
                text: chip.copied ? AgentService.tr("bubble.copied") : chip.label
                font.pixelSize: 9
                color: chip.copied ? chip.copiedColor : chip.fg
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        MouseArea {
            id: chipArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: { chip.requested(); chip.copied = true; chipTimer.restart(); }
        }
    }

    // --- Tooltips for the icon-only buttons ---
    // Drawn inside the chat rather than as a layer of their own: the panel is
    // tall enough that a tip above a toolbar button always fits.
    property string tipText: ""
    property real tipCenterX: 0
    property real tipTopY: 0

    function showTip(item, text) {
        var point = item.mapToItem(chatRoot, item.width / 2, 0);
        tipCenterX = point.x;
        tipTopY = point.y;
        tipText = text;
    }

    function hideTip(text) {
        // Only the tip that is actually showing may hide it: leaving one button
        // for the next often arrives after the next one has already asked.
        if (tipText === text) tipText = "";
    }

    // Dropped inside a button; shows its text after a short hover.
    component TipArea: Item {
        id: tip

        property string text: ""

        anchors.fill: parent

        HoverHandler { id: tipHover }

        Timer {
            id: tipTimer
            interval: 450
            onTriggered: if (tipHover.hovered) chatRoot.showTip(tip, tip.text)
        }

        onEnabledChanged: if (!enabled) chatRoot.hideTip(tip.text)

        Connections {
            target: tipHover
            function onHoveredChanged() {
                if (tipHover.hovered) tipTimer.restart();
                else { tipTimer.stop(); chatRoot.hideTip(tip.text); }
            }
        }
    }

    // Set by the panel: several instances exist (one per bar), only the shown one takes dictation.
    property bool active: true

    // Which monitor this chat belongs to — the position buttons are per-monitor.
    property string screenName: ""

    // Mic button and its twin that listens to the speakers. Both drive the same
    // single recording, so only the one that started it lights up; the other is
    // dimmed meanwhile — two recordings at once would have nothing to transcribe
    // into, and there is one Whisper anyway.
    component CaptureButton: Rectangle {
        id: capture

        property string source: "mic"
        property string idleIcon: "mic"
        property string tip: ""

        readonly property bool active: AgentService.voiceState !== "idle" && AgentService.voiceSource === capture.source
        readonly property bool recording: active && AgentService.voiceState === "recording"
        readonly property bool transcribing: active && AgentService.voiceState === "transcribing"
        readonly property bool otherBusy: AgentService.voiceState !== "idle" && !active
        readonly property bool warmingUp: AgentService.voiceWarmupInProgress

        visible: !AgentService.busy
        width: 32; height: 32; radius: 16
        opacity: otherBusy || warmingUp ? 0.5 : 1
        color: recording ? Theme.withAlpha("#EF4444", 0.18)
            : (captureArea.containsMouse && !otherBusy && !warmingUp ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent")

        DankIcon {
            id: captureIcon
            anchors.centerIn: parent
            name: transcribing ? "progress_activity" : (recording ? "stop" : capture.idleIcon)
            color: recording ? "#EF4444" : (warmingUp ? Theme.withAlpha(Theme.surfaceVariantText, 0.5) : Theme.surfaceVariantText)
            size: 18
            RotationAnimation on rotation {
                running: transcribing; loops: Animation.Infinite
                from: 0; to: 360; duration: 900
                onRunningChanged: if (!running) captureIcon.rotation = 0
            }
        }

        SequentialAnimation on opacity {
            running: capture.recording; loops: Animation.Infinite
            NumberAnimation { to: 0.55; duration: 700; easing.type: Easing.InOutSine }
            NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
            onRunningChanged: if (!running) capture.opacity = capture.otherBusy ? 0.35 : 1
        }

        MouseArea {
            id: captureArea
            anchors.fill: parent
            hoverEnabled: true
            enabled: !capture.transcribing && !capture.otherBusy && !AgentService.voiceWarmupInProgress
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                if (capture.recording) AgentService.stopVoice();
                else AgentService.startVoice(capture.source);
            }
        }

        TipArea { text: capture.tip }
    }

    // One of the three position buttons on the toolbar.
    component PositionButton: Rectangle {
        id: posButton

        property string position: "center"
        property string iconName: ""
        property string tip: ""

        readonly property bool current: AgentService.panelPositionFor(chatRoot.screenName) === posButton.position

        width: 26; height: 26; radius: 13
        color: posButton.current ? Theme.withAlpha(Theme.primary, 0.15)
                                 : (posArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent")

        DankIcon {
            anchors.centerIn: parent
            name: posButton.iconName
            color: posButton.current ? Theme.primary : Theme.surfaceVariantText
            size: 16
        }

        MouseArea {
            id: posArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: AgentService.setPanelPosition(chatRoot.screenName, posButton.position)
        }

        TipArea { text: posButton.tip }
    }

    Timer {
        interval: 5000
        running: AgentService.voiceError !== ""
        onTriggered: AgentService.voiceError = ""
    }

    Timer {
        interval: 5000
        running: AgentService.attachError !== ""
        onTriggered: AgentService.attachError = ""
    }

    // --- Input Card (anchored to bottom) ---
    Rectangle {
        id: inputCard
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: inputCol.height
        radius: 20; color: Theme.withAlpha(Theme.surfaceContainer, AgentService.backgroundOpacity / 100)
        z: 10

        layer.enabled: true
        layer.effect: MultiEffect {
            shadowEnabled: true; shadowBlur: 0.8
            shadowVerticalOffset: -2; shadowColor: Theme.withAlpha(Theme.shadow || "#000000", 0.4)
        }

        ColumnLayout {
            id: inputCol; width: parent.width; spacing: 0

            // Waiting to go with the next message. Click one to open it, the
            // cross drops it.
            Flow {
                Layout.fillWidth: true
                Layout.leftMargin: 14; Layout.rightMargin: 14
                Layout.topMargin: AgentService.pendingAttachments.length > 0 ? 12 : 0
                spacing: 8
                visible: AgentService.pendingAttachments.length > 0

                Repeater {
                    model: AgentService.pendingAttachments

                    Rectangle {
                        required property var modelData

                        readonly property string path: modelData.path
                        readonly property string fileName: path.substring(path.lastIndexOf("/") + 1)
                        readonly property bool isImage: /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(path)

                        width: isImage ? 84 : Math.min(150, nameText.implicitWidth + 40)
                        height: 58; radius: 8
                        clip: true
                        color: Theme.surfaceVariant
                        border.width: 1
                        border.color: attachArea.containsMouse ? Theme.primary : Theme.withAlpha(Theme.outlineVariant, 0.5)

                        Image {
                            visible: parent.isImage
                            anchors.fill: parent
                            anchors.margins: 1
                            source: parent.isImage ? "file://" + parent.path : ""
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            cache: false
                        }

                        Column {
                            visible: !parent.isImage
                            anchors.centerIn: parent
                            width: parent.width - 16
                            spacing: 2

                            DankIcon {
                                anchors.horizontalCenter: parent.horizontalCenter
                                name: "description"; size: 20; color: Theme.surfaceVariantText
                            }

                            Text {
                                id: nameText
                                width: parent.width
                                text: fileName
                                font.pixelSize: 9
                                color: Theme.surfaceText
                                elide: Text.ElideMiddle
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }

                        MouseArea {
                            id: attachArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: AgentService.openAttachment(parent.path)
                        }

                        Rectangle {
                            anchors.top: parent.top; anchors.right: parent.right
                            anchors.margins: 2
                            width: 16; height: 16; radius: 8
                            color: dropAttachArea.containsMouse ? Theme.error || "#EF4444"
                                                                : Theme.withAlpha(Theme.shadow || "#000000", 0.6)

                            DankIcon {
                                anchors.centerIn: parent
                                name: "close"; size: 11; color: "#FFFFFF"
                            }

                            MouseArea {
                                id: dropAttachArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: AgentService.removeAttachment(parent.parent.path)
                            }
                        }
                    }
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(44, inputField.contentHeight + 24)

                // Opens the desktop's own file chooser — the same dialog a
                // browser shows for "choose a file".
                Rectangle {
                    id: attachButton
                    width: 28; height: 28; radius: 14
                    anchors.left: parent.left; anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    color: attachBtnArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.35) : "transparent"

                    DankIcon {
                        anchors.centerIn: parent
                        name: "attach_file"; size: 16
                        color: Theme.surfaceVariantText
                    }

                    MouseArea {
                        id: attachBtnArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: AgentService.pickFiles()
                    }

                    TipArea { text: AgentService.tr("tip.attach") }
                }

                TextEdit {
                    id: inputField
                    anchors.fill: parent
                    anchors.leftMargin: 46; anchors.rightMargin: 18
                    anchors.topMargin: 12; anchors.bottomMargin: 12
                    color: Theme.surfaceText; font.pixelSize: 14
                    wrapMode: TextEdit.Wrap; clip: true

                    Text {
                        visible: !inputField.text && !inputField.activeFocus
                        text: AgentService.tr("input.placeholder")
                        color: Theme.surfaceVariantText; font.pixelSize: 14
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Keys.onReturnPressed: function(event) {
                        if (event.modifiers & Qt.ShiftModifier) event.accepted = false;
                        else { event.accepted = true; sendCurrentMessage(); }
                    }

                    Keys.onEscapePressed: function(event) {
                        event.accepted = true;
                        if (AgentService.voiceState === "recording") AgentService.cancelVoice();
                        else chatRoot.escapePressed();
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
                            Text { text: AgentService.tr("toolbar.think"); font.pixelSize: 11; color: AgentService.extendedThinking ? Theme.primary : Theme.surfaceVariantText; anchors.verticalCenter: parent.verticalCenter }
                        }
                        MouseArea { id: thinkArea; anchors.fill: parent; hoverEnabled: true; onClicked: AgentService.extendedThinking = !AgentService.extendedThinking }
                    }

                    // New chat
                    Rectangle {
                        width: 26; height: 26; radius: 13
                        color: newChatArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent"
                        DankIcon { anchors.centerIn: parent; name: "add"; color: Theme.surfaceVariantText; size: 16 }
                        MouseArea { id: newChatArea; anchors.fill: parent; hoverEnabled: true; onClicked: { AgentService.clearMessages(); AgentService.clearAttachments(false); messageModel.clear(); } }
                        TipArea { text: AgentService.tr("tip.newChat") }
                    }

                    // History
                    Rectangle {
                        width: 26; height: 26; radius: 13
                        color: historyArea.containsMouse || historyDropdown.visible ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent"
                        DankIcon { anchors.centerIn: parent; name: "history"; color: Theme.surfaceVariantText; size: 16 }
                        MouseArea { id: historyArea; anchors.fill: parent; hoverEnabled: true; onClicked: { AgentService.loadHistory(); historyDropdown.visible = !historyDropdown.visible; } }
                        TipArea { text: AgentService.tr("tip.history") }
                    }

                    // Where the chat window sits on this monitor.
                    PositionButton { position: "left";   iconName: "align_horizontal_left";   tip: AgentService.tr("tip.posLeft") }
                    PositionButton { position: "center"; iconName: "align_horizontal_center"; tip: AgentService.tr("tip.posCenter") }
                    PositionButton { position: "right";  iconName: "align_horizontal_right";  tip: AgentService.tr("tip.posRight") }

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
                            TipArea { text: AgentService.tr("tip.stop") }
                        }
                    }

                    // Voice input: error, recording timer, mic button
                    Text {
                        visible: (AgentService.voiceError !== "" || AgentService.attachError !== "") && !AgentService.busy
                        text: AgentService.voiceError || AgentService.attachError
                        color: Theme.error || "#EF4444"; font.pixelSize: 10
                        elide: Text.ElideRight; Layout.maximumWidth: 240
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Text {
                        visible: AgentService.voiceState === "recording"
                        text: Math.floor(AgentService.voiceSeconds / 60) + ":" + ("0" + AgentService.voiceSeconds % 60).slice(-2)
                        color: "#EF4444"; font.pixelSize: 11; font.family: "monospace"
                        Layout.alignment: Qt.AlignVCenter
                    }

                    // Attaches a shot of the focused window to the next message,
                    // so the agent can see what the other side is showing.
                    Rectangle {
                        id: shotButton
                        visible: !AgentService.busy
                        width: 32; height: 32; radius: 16
                        Layout.alignment: Qt.AlignVCenter
                        readonly property bool armed: AgentService.pendingAttachments.some(function(a) { return a.kind === "shot"; })
                        color: armed ? Theme.withAlpha(Theme.primary, 0.15)
                            : (shotBtnArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent")

                        DankIcon {
                            anchors.centerIn: parent
                            name: "photo_camera"
                            color: shotButton.armed ? Theme.primary : Theme.surfaceVariantText
                            size: 18
                        }

                        MouseArea {
                            id: shotBtnArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: AgentService.captureWindow()
                        }

                        TipArea { text: AgentService.tr("tip.screenshot") }
                    }

                    // Listens to the speakers instead of the microphone — for
                    // transcribing the other side of a call when headphones keep
                    // them out of the mic.
                    CaptureButton {
                        source: "output"
                        idleIcon: "hearing"
                        tip: AgentService.tr("tip.listenOutput")
                        Layout.alignment: Qt.AlignVCenter
                    }

                    CaptureButton {
                        source: "mic"
                        idleIcon: "mic"
                        tip: AgentService.tr("tip.mic")
                        Layout.alignment: Qt.AlignVCenter
                    }

                    Rectangle {
                        visible: !AgentService.busy
                        width: 32; height: 32; radius: 16
                        color: canSend ? Theme.primary : Theme.withAlpha(Theme.surfaceVariant, 0.2)
                        property bool canSend: inputField.text.trim().length > 0
                        DankIcon { anchors.centerIn: parent; name: "arrow_upward"; color: parent.canSend ? Theme.primaryText : Theme.surfaceVariantText; size: 18 }
                        MouseArea { anchors.fill: parent; onClicked: if (parent.canSend) sendCurrentMessage() }
                        TipArea { text: AgentService.tr("tip.send") }
                    }
                }
            }
        }
    }

    // Above the input card and its dropdowns, so it is never clipped by them.
    Rectangle {
        id: tipBubble
        visible: chatRoot.tipText !== ""
        z: 50

        width: tipLabel.implicitWidth + 16
        height: tipLabel.implicitHeight + 10
        radius: 6
        color: Theme.surfaceContainerHighest
        border.width: 1
        border.color: Theme.withAlpha(Theme.outlineVariant, 0.6)

        x: Math.max(4, Math.min(chatRoot.width - width - 4, chatRoot.tipCenterX - width / 2))
        y: chatRoot.tipTopY - height - 6

        Text {
            id: tipLabel
            anchors.centerIn: parent
            text: chatRoot.tipText
            font.pixelSize: 11
            color: Theme.surfaceText
        }
    }

    // --- Neon rims (behind the cards they outline) ---
    NeonBorder { target: inputCard; radius: 20 }
    NeonBorder { target: modelDropdown; radius: 12; glowOpacity: 0.45 }
    NeonBorder { target: historyDropdown; radius: 12; glowOpacity: 0.45 }

    // --- Model Dropdown (outside input card, z on top) ---
    Rectangle {
        id: modelDropdown; visible: false
        anchors.bottom: inputCard.top; anchors.bottomMargin: 6
        anchors.left: inputCard.left; anchors.leftMargin: 8
        width: 130; height: modelCol.height + 8; radius: 12
        color: Theme.surfaceContainerHighest
        z: 20

        Column {
            id: modelCol; anchors.top: parent.top; anchors.topMargin: 4
            anchors.left: parent.left; anchors.right: parent.right
            Repeater {
                model: [{ id: "haiku", label: "Haiku", desc: AgentService.tr("model.fast") }, { id: "sonnet", label: "Sonnet", desc: AgentService.tr("model.balanced") }, { id: "opus", label: "Opus", desc: AgentService.tr("model.best") }]
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
        color: Theme.surfaceContainerHighest
        z: 20

        Text {
            visible: AgentService.history.length === 0
            text: AgentService.tr("history.empty"); color: Theme.surfaceVariantText; font.pixelSize: 12
            anchors.centerIn: parent
        }

        // Clears every stored conversation — behind a confirmation, like the
        // per-row crosses.
        Rectangle {
            id: clearAllButton
            visible: AgentService.history.length > 0
            anchors.top: parent.top; anchors.right: parent.right
            anchors.topMargin: 6; anchors.rightMargin: 8
            width: clearAllRow.width + 16; height: 24; radius: 12
            z: 2
            color: clearAllArea.containsMouse ? Theme.withAlpha(Theme.error || "#EF4444", 0.15) : "transparent"
            border.width: 1
            border.color: Theme.withAlpha(Theme.outlineVariant, 0.5)

            Row {
                id: clearAllRow
                anchors.centerIn: parent
                spacing: 4
                DankIcon {
                    name: "delete"; size: 13
                    color: clearAllArea.containsMouse ? (Theme.error || "#EF4444") : Theme.surfaceVariantText
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: AgentService.tr("history.clearAll"); font.pixelSize: 10
                    color: clearAllArea.containsMouse ? (Theme.error || "#EF4444") : Theme.surfaceVariantText
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            MouseArea {
                id: clearAllArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: chatRoot.askDeleteAll()
            }
        }

        ListView {
            anchors.fill: parent; anchors.margins: 4; anchors.topMargin: 34; clip: true; spacing: 0
            visible: AgentService.history.length > 0
            model: AgentService.history
            delegate: Rectangle {
                width: ListView.view.width; height: 36; radius: 8
                color: hArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.3) : "transparent"
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 8; spacing: 8
                    Text { text: modelData.title || "Chat"; font.pixelSize: 12; color: Theme.surfaceText; elide: Text.ElideRight; Layout.fillWidth: true }
                    Text {
                        text: { var d = new Date(modelData.date); return d.toLocaleDateString(undefined, {month:"short", day:"numeric"}) }
                        font.pixelSize: 10; color: Theme.surfaceVariantText
                    }

                    // Above the row's own MouseArea, so it takes the click instead
                    // of opening the conversation.
                    Rectangle {
                        Layout.preferredWidth: 20; Layout.preferredHeight: 20
                        radius: 10
                        color: dropRowArea.containsMouse ? Theme.withAlpha(Theme.error || "#EF4444", 0.2) : "transparent"
                        opacity: dropRowArea.containsMouse ? 1 : (hArea.containsMouse ? 0.9 : 0.45)
                        Behavior on opacity { NumberAnimation { duration: 100 } }

                        DankIcon {
                            anchors.centerIn: parent
                            name: "close"; size: 12
                            color: dropRowArea.containsMouse ? (Theme.error || "#EF4444") : Theme.surfaceVariantText
                        }

                        MouseArea {
                            id: dropRowArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: chatRoot.askDeleteSession(modelData.id, modelData.title || "Chat")
                        }
                    }
                }
                MouseArea { id: hArea; anchors.fill: parent; hoverEnabled: true; z: -1; onClicked: { messageModel.clear(); AgentService.resumeSession(modelData.id); historyDropdown.visible = false; } }
            }
        }
    }

    // --- Confirmation for deleting history ---
    // Transcripts are removed from disk with no copy anywhere, so both the
    // crosses and "Clear all" come through here first.
    property string confirmSessionId: ""
    property string confirmText: ""

    function askDeleteSession(id, title) {
        confirmSessionId = id;
        confirmText = AgentService.tr("confirm.deleteOne") + "\n\n" + title;
        confirmDialog.visible = true;
    }

    function askDeleteAll() {
        confirmSessionId = "";
        confirmText = AgentService.tr("confirm.deleteAll", { n: AgentService.history.length })
            + "\n\n" + AgentService.tr("confirm.irreversible");
        confirmDialog.visible = true;
    }

    Rectangle {
        id: confirmDialog
        visible: false
        anchors.fill: parent
        color: Theme.withAlpha(Theme.shadow || "#000000", 0.55)
        z: 40

        // Swallows clicks so nothing behind the dialog reacts.
        MouseArea { anchors.fill: parent; hoverEnabled: true; onClicked: confirmDialog.visible = false }

        Rectangle {
            width: Math.min(parent.width - 48, 340)
            height: confirmCol.height + 32
            anchors.centerIn: parent
            radius: 16
            color: Theme.surfaceContainerHighest
            border.width: 1
            border.color: Theme.withAlpha(Theme.outlineVariant, 0.5)

            MouseArea { anchors.fill: parent }

            Column {
                id: confirmCol
                anchors.centerIn: parent
                width: parent.width - 32
                spacing: 16

                Text {
                    width: parent.width
                    text: chatRoot.confirmText
                    wrapMode: Text.Wrap
                    color: Theme.surfaceText
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8

                    Rectangle {
                        width: 92; height: 30; radius: 15
                        color: cancelBtnArea.containsMouse ? Theme.withAlpha(Theme.surfaceVariant, 0.5) : Theme.withAlpha(Theme.surfaceVariant, 0.25)
                        Text {
                            anchors.centerIn: parent; text: AgentService.tr("confirm.cancel")
                            font.pixelSize: 12; color: Theme.surfaceText
                        }
                        MouseArea {
                            id: cancelBtnArea
                            anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: confirmDialog.visible = false
                        }
                    }

                    Rectangle {
                        width: 92; height: 30; radius: 15
                        color: deleteBtnArea.containsMouse ? (Theme.error || "#EF4444") : Theme.withAlpha(Theme.error || "#EF4444", 0.8)
                        Text {
                            anchors.centerIn: parent; text: AgentService.tr("confirm.delete")
                            font.pixelSize: 12; font.weight: Font.Bold; color: "#FFFFFF"
                        }
                        MouseArea {
                            id: deleteBtnArea
                            anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (chatRoot.confirmSessionId === "") AgentService.deleteAllSessions();
                                else AgentService.deleteSession(chatRoot.confirmSessionId);
                                confirmDialog.visible = false;
                                messageModel.clear();
                            }
                        }
                    }
                }
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

    // Bubbles use TextEdit rather than Text: only TextEdit can be selected with
    // the mouse. It is read-only, so it behaves like a label that happens to be
    // selectable. The natural width is measured by a hidden Text alongside it —
    // asking TextEdit for its implicitWidth while its own width comes from the
    // bubble would be a binding loop.
    // The top and bottom margins are symmetrical (10px each). Copy chips float
    // as an overlay in the bottom right corner when hovered.
    readonly property int bubbleActionStrip: 0

    Component {
        id: userComp
        Item {
            height: uRect.height

            Text {
                id: uMetric
                visible: false
                text: content
                font.pixelSize: AgentService.bubbleFontSize
            }

            Rectangle {
                id: uRect; anchors.right: parent.right
                width: Math.min(parent.width * 0.8, uMetric.implicitWidth + 28)
                height: uTxt.implicitHeight + 11
                radius: 16; color: Theme.withAlpha(Theme.primary, AgentService.backgroundOpacity / 100)

                HoverHandler { id: uHover }

                TextEdit {
                    id: uTxt
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                    anchors.leftMargin: 14; anchors.rightMargin: 14; anchors.topMargin: 8
                    padding: 0
                    topPadding: 0
                    bottomPadding: 0
                    text: content
                    wrapMode: TextEdit.Wrap
                    color: Theme.primaryText
                    font.pixelSize: AgentService.bubbleFontSize
                    readOnly: true
                    selectByMouse: true
                    persistentSelection: true
                    selectionColor: Theme.withAlpha(Theme.primaryText, 0.3)
                    selectedTextColor: Theme.primaryText

                    Keys.onEscapePressed: function(event) {
                        event.accepted = true;
                        uTxt.deselect();
                        inputField.forceActiveFocus();
                    }
                }

                CopyChip {
                    anchors.right: parent.right; anchors.rightMargin: 8
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                    opacity: uHover.hovered ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 120 } }

                    label: AgentService.tr("bubble.copyText")
                    fg: Theme.primary
                    bg: Theme.primaryText
                    copiedColor: Theme.primary
                    onRequested: chatRoot.copyToClipboard(content)
                }
            }
        }
    }

    Component {
        id: assistantComp
        Item {
            height: aRect.height

            Text {
                id: aMetric
                visible: false
                text: Md.markdownToHtml(content)
                textFormat: Text.RichText
                font.pixelSize: AgentService.bubbleFontSize
            }

            Rectangle {
                id: aRect; anchors.left: parent.left
                width: Math.min(parent.width * 0.85, aMetric.implicitWidth + 28)
                height: aTxt.implicitHeight + 16
                radius: 16; color: Theme.withAlpha(Theme.surfaceContainer, AgentService.backgroundOpacity / 100)

                HoverHandler { id: aHover }

                TextEdit {
                    id: aTxt
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                    anchors.leftMargin: 14; anchors.rightMargin: 14; anchors.topMargin: 8
                    padding: 0
                    topPadding: 0
                    bottomPadding: 0
                    text: Md.markdownToHtml(content)
                    textFormat: TextEdit.RichText
                    wrapMode: TextEdit.Wrap
                    color: Theme.surfaceText
                    font.pixelSize: AgentService.bubbleFontSize
                    readOnly: true
                    selectByMouse: true
                    persistentSelection: true
                    selectionColor: Theme.primary
                    selectedTextColor: Theme.primaryText

                    Keys.onEscapePressed: function(event) {
                        event.accepted = true;
                        aTxt.deselect();
                        inputField.forceActiveFocus();
                    }
                }

                Row {
                    anchors.right: parent.right; anchors.rightMargin: 8
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                    spacing: 6
                    opacity: aHover.hovered ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 120 } }

                    // "md" keeps what the agent actually sent — headings, bold,
                    // fenced code. "Text" is what the bubble shows, without markup.
                    CopyChip {
                        label: AgentService.tr("bubble.copyMarkdown")
                        onRequested: chatRoot.copyToClipboard(content)
                    }

                    CopyChip {
                        label: AgentService.tr("bubble.copyText")
                        onRequested: chatRoot.copyToClipboard(aTxt.getText(0, aTxt.length))
                    }
                }
            }
        }
    }

    function sendCurrentMessage() {
        var text = inputField.text.trim();
        var items = AgentService.pendingAttachments;
        if ((!text && items.length === 0) || AgentService.busy) return;

        // Attachments reach the agent as paths it opens itself. Screenshots and
        // chosen files are worded differently: one is "what is on screen", the
        // other is a file, and the agent should not confuse them.
        var sent = text;
        if (items.length > 0) {
            var shots = [], files = [];
            for (var i = 0; i < items.length; i++)
                (items[i].kind === "shot" ? shots : files).push(items[i].path);

            var lines = [];
            if (shots.length > 0)
                lines.push(AgentService.tr(shots.length === 1 ? "prompt.oneImage" : "prompt.manyImages",
                                           { paths: shots.join(", ") }));
            if (files.length > 0)
                lines.push(AgentService.tr(files.length === 1 ? "prompt.oneFile" : "prompt.manyFiles",
                                           { paths: files.join(", ") }));

            sent = lines.join("\n") + (text ? "\n\n" + text : "");
        }

        inputField.text = "";
        AgentService.clearAttachments(true);
        AgentService.sendMessage(sent);
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

        function onVoiceTextReady(text, isFirstChunk) {
            if (!chatRoot.active) return;
            var currentText = inputField.text;
            var sep = "";
            if (currentText.length > 0) {
                sep = isFirstChunk ? "\n\n" : "\n";
            }
            inputField.text = currentText + sep + text;
            inputField.cursorPosition = inputField.text.length;
            inputField.forceActiveFocus();
        }

        function onMessageAdded(message) {
            if (message.role === "tool" || message.role === "tool_result") return;
            messageModel.append({ msgRole: message.role, msgContent: message.content, msgTimestamp: message.timestamp });
        }
    }
}
