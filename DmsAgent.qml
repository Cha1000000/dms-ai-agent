import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Io
import qs.Common
import qs.Widgets
import qs.Modules.Plugins

PluginComponent {
    id: root

    layerNamespacePlugin: "dmsAgent"

    // Every bar gets its own instance, so the chat opens on the monitor of the
    // pill that was clicked. AgentService keeps only one panel visible at a time
    // and owns the IPC handler (a per-instance one would be registered twice).
    readonly property string screenName: parentScreen ? parentScreen.name : ""

    Connections {
        target: AgentService
        function onPanelRequested(name) {
            var mine = name === root.screenName || (name === "*" && AgentService.visibleScreen === "");
            if (mine) agentPanel.show();
            else if (agentPanel.isVisible) agentPanel.hide();
        }
        function onPanelHideRequested() {
            if (agentPanel.isVisible) agentPanel.hide();
        }
    }

    // "AI" in a square with sparkles; painted in the given color so it follows the theme.
    function aiIconSource(color) {
        var c = "rgb(" + Math.round(color.r * 255) + "," + Math.round(color.g * 255) + "," + Math.round(color.b * 255) + ")";
        var svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
            + "<path d='M50,21 H26 A13,13 0 0 0 13,34 V77 A13,13 0 0 0 26,90 H67 A13,13 0 0 0 80,77 V49' fill='none' stroke='" + c + "' stroke-width='7.5'/>"
            + "<path fill='" + c + "' fill-rule='evenodd' d='"
            + "M28,76 L38.5,41 H46.5 L57,76 H49.8 L47.6,68.5 H37.4 L35.2,76 Z M39.2,62.5 H45.8 L42.5,50.5 Z "
            + "M62,41 H69 V76 H62 Z "
            + "M65,3 Q67.2,12.8 77,15 Q67.2,17.2 65,27 Q62.8,17.2 53,15 Q62.8,12.8 65,3Z "
            + "M89,5.5 Q90,10 94.5,11 Q90,12 89,16.5 Q88,12 83.5,11 Q88,10 89,5.5Z "
            + "M85,25.5 Q86.5,32.5 93.5,34 Q86.5,35.5 85,42.5 Q83.5,35.5 76.5,34 Q83.5,32.5 85,25.5Z"
            + "'/></svg>";
        return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
    }

    // Chat position is picked with the buttons in the chat itself, not in the
    // settings window, so it lives in plugin state rather than plugin data.
    // Loaded once: both instances share the singleton that holds it.
    // pluginService and pluginId are still empty while Component.onCompleted runs
    // (the same way parentScreen is), so the load is driven by them arriving.
    function loadPanelPositions() {
        if (AgentService.positionsLoaded || !pluginService || !pluginId) return;
        AgentService.panelPositions = pluginService.loadPluginState(pluginId, "panelPositions", {}) || {};
        AgentService.positionsLoaded = true;
    }

    onPluginServiceChanged: loadPanelPositions()

    Connections {
        target: AgentService
        function onPanelPositionChanged(name, position) {
            // Only the instance whose monitor changed writes, so one click is one write.
            if (name !== root.screenName || !root.pluginService) return;
            root.pluginService.savePluginState(root.pluginId, "panelPositions", AgentService.panelPositions);
        }
    }

    onPluginDataChanged: {
        loadPanelPositions();
        if (!pluginData) return;
        AgentService.claudeModel = pluginData.claudeModel || "haiku";
        AgentService.maxTokens = parseInt(pluginData.maxTokens) || 1024;
        AgentService.bubbleFontSize = parseInt(pluginData.bubbleFontSize) || 13;
        AgentService.extendedThinking = pluginData.extendedThinking === true;
        if (pluginData.systemPrompt) AgentService.systemPrompt = pluginData.systemPrompt;
        AgentService.pillLabel = pluginData.pillLabel || "Jarvis";
        AgentService.voiceModel = pluginData.voiceModel || "auto";
        AgentService.voiceLanguage = pluginData.voiceLanguage || "auto";
        AgentService.voiceVenv = pluginData.voiceVenv || "";
        AgentService.voiceDevice = pluginData.voiceDevice || "";
        AgentService.autoUpdate = pluginData.autoUpdate !== false;
        AgentService.checkForUpdates();
        if (pluginData.hotkey !== undefined) AgentService.applyHotkey(pluginData.hotkey);
    }

    PanelWindow {
        id: agentPanel

        property bool isVisible: false

        function show() {
            // The other instance's chat may have missed a "new chat" / history
            // switch while hidden, so the feed is rebuilt from the shared state.
            agentChat.reloadMessages();
            visible = true; isVisible = true; AgentService.setPanelVisible(root.screenName, true);
            animScale = 1.0; animOpacity = 1.0;
        }
        function hide() {
            // Closing the chat mid-dictation drops the recording.
            if (AgentService.voiceState === "recording") AgentService.cancelVoice();
            isVisible = false; AgentService.setPanelVisible(root.screenName, false);
            animScale = 0.92; animOpacity = 0.0;
        }
        function toggle() {
            if (isVisible) hide();
            else AgentService.showPanelOn(root.screenName);
        }

        property real animScale: 0.92
        property real animOpacity: 0.0

        visible: isVisible || hideAnim.running || scaleAnim.running
        screen: root.parentScreen || (Quickshell.screens.length > 0 ? Quickshell.screens[0] : null)
        color: "transparent"

        readonly property string panelPosition: AgentService.panelPositionFor(root.screenName)

        // With neither side anchored the compositor centres the window; anchoring
        // one side pins it there. That is the whole of the left/centre/right choice.
        anchors.bottom: true
        anchors.left: panelPosition === "left"
        anchors.right: panelPosition === "right"

        WlrLayershell.layer: WlrLayershell.Top
        WlrLayershell.namespace: "dms:agent"
        WlrLayershell.exclusiveZone: 0
        WlrLayershell.keyboardFocus: isVisible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
        WlrLayershell.margins.bottom: 44

        implicitWidth: 660
        implicitHeight: 740

        Item {
            id: animContainer
            anchors.fill: parent
            anchors.margins: 10
            scale: agentPanel.animScale
            opacity: agentPanel.animOpacity
            transformOrigin: Item.Bottom

            DmsAgentChat {
                id: agentChat
                active: agentPanel.isVisible
                screenName: root.screenName
                anchors.fill: parent
                onEscapePressed: agentPanel.hide()
            }
        }

        Behavior on animScale {
            NumberAnimation { id: scaleAnim; duration: 250; easing.type: Easing.OutCubic }
        }

        Behavior on animOpacity {
            NumberAnimation {
                id: hideAnim; duration: 200; easing.type: Easing.OutCubic
                onRunningChanged: { if (!running && !agentPanel.isVisible) agentPanel.visible = false; }
            }
        }
    }

    horizontalBarPill: Component {
        Row {
            spacing: Theme.spacingXS
            DankIcon {
                visible: AgentService.busy
                name: "hourglass_top"; color: "#FF9800"
                size: root.iconSize; anchors.verticalCenter: parent.verticalCenter
            }
            Image {
                visible: !AgentService.busy
                source: root.aiIconSource(Theme.primary)
                width: root.iconSize; height: root.iconSize
                sourceSize: Qt.size(root.iconSize * 2, root.iconSize * 2)
                smooth: true; anchors.verticalCenter: parent.verticalCenter
            }
            StyledText {
                anchors.verticalCenter: parent.verticalCenter
                text: AgentService.busy ? "Working..." : AgentService.pillLabel
                color: Theme.surfaceText; font.pixelSize: Theme.fontSizeSmall
            }
        }
    }

    verticalBarPill: Component {
        Column {
            spacing: 2
            DankIcon {
                visible: AgentService.busy
                name: "hourglass_top"; color: "#FF9800"
                size: root.iconSize; anchors.horizontalCenter: parent.horizontalCenter
            }
            Image {
                visible: !AgentService.busy
                source: root.aiIconSource(Theme.primary)
                width: root.iconSize; height: root.iconSize
                sourceSize: Qt.size(root.iconSize * 2, root.iconSize * 2)
                smooth: true; anchors.horizontalCenter: parent.horizontalCenter
            }
            StyledText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: AgentService.busy ? "..." : "AI"
                color: Theme.surfaceText; font.pixelSize: Theme.fontSizeSmall
            }
        }
    }

    pillClickAction: function() {
        agentPanel.toggle();
    }
}
