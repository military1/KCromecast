import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid

PlasmoidItem {
    id: root
    property var devices: []
    property var sleepTimer: ({ remaining: 0, device: "", minutes: 0 })
    property bool online: false
    property bool reading: false
    property int pendingCommands: 0
    property real lastSample: 0
    property string errorText: ""
    readonly property bool busy: pendingCommands > 0
    readonly property string selectedId: Plasmoid.configuration.preferredDevice
    readonly property var device: devices.find(d => d.id === selectedId) || ({})
    readonly property bool available: online && !!device.connected
    readonly property bool active: available && ["PLAYING", "PAUSED", "BUFFERING"].includes(device.state)
    readonly property bool playing: active && device.state !== "PAUSED"
    readonly property int sleepRemaining: sleepTimer.device === selectedId ? sleepTimer.remaining : 0
    readonly property bool reducedMotion: Plasmoid.configuration.reduceMotion

    Plasmoid.title: "KCromecast"
    Plasmoid.icon: Qt.resolvedUrl("../icons/kcromecast.svg")
    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground
    Plasmoid.onActivated: root.expanded = !root.expanded
    preferredRepresentation: compactRepresentation
    toolTipMainText: root.active ? root.device.title || "KCromecast" : "KCromecast"
    toolTipSubText: root.active ? (root.device.artist || "") + "\n" + (root.device.name || "")
        + "\n" + i18n("Middle-click: pause · Scroll: volume")
        : i18n("Music on your speakers. Control from here.")

    function formatTime(value) {
        var seconds = Math.max(0, Math.floor(Number(value) || 0));
        var minutes = Math.floor(seconds / 60);
        return minutes + ":" + String(seconds % 60).padStart(2, "0");
    }

    function applySnapshot(data) {
        if ((data.sampled_at || 0) < root.lastSample) return;
        root.lastSample = data.sampled_at || 0;
        root.online = true;
        root.devices = data.devices || [];
        root.sleepTimer = data.sleep || ({ remaining: 0, device: "" });
        if (data.error) root.errorText = data.error;
        if (!root.selectedId && root.devices.length) {
            var active = root.devices.find(d => d.group && d.state !== "IDLE")
                || root.devices.find(d => d.state !== "IDLE") || root.devices[0];
            Plasmoid.configuration.preferredDevice = active.id;
        }
    }

    function request(method, path, data, done) {
        var xhr = new XMLHttpRequest();
        xhr.open(method, "http://127.0.0.1:17844/v1/" + path);
        xhr.setRequestHeader("Authorization", "Bearer " + Plasmoid.configuration.backendToken);
        if (method === "POST") xhr.setRequestHeader("Content-Type", "application/json");
        var finished = false;
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || finished) return;
            finished = true;
            var response = {};
            try { response = JSON.parse(xhr.responseText); } catch (e) {}
            if (xhr.status === 200) root.applySnapshot(response);
            else if (method === "GET") root.online = false;
            if (done) done(xhr.status, response);
        };
        xhr.send(data === null ? "" : JSON.stringify(data));
    }

    function refresh() {
        if (root.reading) return;
        root.reading = true;
        root.request("GET", "state", null, function() { root.reading = false; });
    }

    function selectDevice(id) {
        Plasmoid.configuration.preferredDevice = id;
        root.errorText = "";
    }

    function send(action, value) {
        if (!root.available) return;
        root.pendingCommands++;
        root.errorText = "";
        root.request("POST", "command", { device: root.selectedId, action: action, value: value }, function(status, response) {
            root.pendingCommands--;
            if (status !== 200) {
                root.errorText = response.error || i18n("The speakers did not respond. Try again.");
                dismissError.restart();
            }
        });
    }

    Timer {
        interval: root.expanded ? 1000 : 5000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }
    Timer { id: dismissError; interval: 10000; onTriggered: root.errorText = "" }
    onExpandedChanged: function(value) { if (value) root.refresh(); }

    compactRepresentation: MouseArea {
        id: compact
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        property int volumeDelta: 0
        onClicked: mouse => {
            if (mouse.button === Qt.MiddleButton && root.active) root.send("toggle");
            else root.expanded = !root.expanded;
        }
        onWheel: wheel => {
            if (root.available) {
                volumeDelta = Math.max(-10, Math.min(10, volumeDelta + (wheel.angleDelta.y > 0 ? 2 : -2)));
                volumeWheel.restart();
            }
            wheel.accepted = true;
        }
        Timer {
            id: volumeWheel
            interval: 140
            onTriggered: { root.send("volume_delta", compact.volumeDelta); compact.volumeDelta = 0; }
        }
        Image {
            anchors.fill: parent
            anchors.margins: 2
            source: Qt.resolvedUrl("../icons/kcromecast.svg")
            fillMode: Image.PreserveAspectFit
            smooth: true
            opacity: compact.containsMouse ? 1 : 0.9
        }
        Rectangle {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 3
            width: 8; height: 8; radius: 4
            visible: root.active
            color: root.playing ? "#7ce6b3" : "#f2cf87"
            border.color: Kirigami.Theme.backgroundColor
            border.width: 1
        }
    }

    fullRepresentation: Player {
        controller: root
    }
}
