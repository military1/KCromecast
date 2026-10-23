import "Locale.js" as L10n
import "SnapshotOrder.js" as SnapshotOrder
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
    property var requests: []
    property var commandQueue: []
    property bool commandRunning: false
    property bool closing: false
    property bool selectionSynced: false
    property bool hadConnection: false
    property var snapshotOrder: SnapshotOrder.create()
    property real sampledAt: 0
    property real displayClock: Date.now()
    property var spotify: ({connected: false, client_id: "", error: ""})
    property string errorText: ""
    readonly property bool busy: commandRunning
    readonly property string selectedId: Plasmoid.configuration.preferredDevice
    readonly property var device: devices.find(d => d.id === selectedId) || ({})
    readonly property bool available: online && !!device.connected
    readonly property bool active: available && ["PLAYING", "PAUSED", "BUFFERING"].includes(device.state)
    readonly property bool playing: active && device.state !== "PAUSED"
    readonly property int sleepRemaining: sleepTimer.device === selectedId
        ? Math.max(0, Math.ceil((sleepTimer.deadline * 1000 - displayClock) / 1000)) : 0
    readonly property real playbackPosition: {
        var position = Number(device.position) || 0;
        if (playing && device.state === "PLAYING") position += Math.max(0, (displayClock - sampledAt) / 1000);
        return device.duration ? Math.min(position, device.duration) : position;
    }
    readonly property bool reducedMotion: Plasmoid.configuration.reduceMotion

    Plasmoid.title: "KCromecast"
    Plasmoid.icon: Qt.resolvedUrl("../icons/kcromecast.svg")
    Plasmoid.status: PlasmaCore.Types.ActiveStatus
    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground
    Plasmoid.onActivated: root.expanded = !root.expanded
    preferredRepresentation: compactRepresentation
    toolTipMainText: root.active ? root.device.title || "KCromecast" : "KCromecast"
    toolTipSubText: root.active ? (root.device.artist || "") + "\n" + (root.device.name || "")
        + "\n" + L10n.tr(Qt.locale(), "Middle-click: pause · Scroll: volume")
        : L10n.tr(Qt.locale(), "Music on your speakers. Control from here.")

    function formatTime(value) {
        var seconds = Math.max(0, Math.floor(Number(value) || 0));
        var minutes = Math.floor(seconds / 60);
        return minutes + ":" + String(seconds % 60).padStart(2, "0");
    }

    function applySnapshot(data) {
        if (!SnapshotOrder.accept(root.snapshotOrder, data)) return;
        root.sampledAt = Date.now();
        root.displayClock = root.sampledAt;
        root.hadConnection = true;
        root.online = true;
        if (JSON.stringify(root.devices) !== JSON.stringify(data.devices || [])) root.devices = data.devices || [];
        root.spotify = data.spotify || ({connected: false, client_id: "", error: ""});
        root.sleepTimer = data.sleep || ({ remaining: 0, device: "" });
        if (data.error) root.errorText = L10n.tr(Qt.locale(), data.error);
        if (!root.selectionSynced && root.selectedId && root.devices.some(d => d.id === root.selectedId)) {
            root.selectionSynced = true;
            if (data.selected !== root.selectedId) root.selectDevice(root.selectedId);
        } else if (!root.selectedId || root.selectionSynced) {
            if (data.selected) Plasmoid.configuration.preferredDevice = data.selected;
        }
    }

    function request(method, path, data, done) {
        if (root.closing) return;
        var xhr = new XMLHttpRequest();
        var finished = false;
        var item = {xhr: xhr, deadline: Date.now() + (method === "GET" ? 5000 : 25000)};
        function finish() {
            if (finished || root.closing) return;
            finished = true;
            root.requests = root.requests.filter(r => r !== item);
            var response = {};
            try { response = JSON.parse(xhr.responseText); } catch (error) {}
            if (xhr.status === 200 && response.instance) root.applySnapshot(response);
            else if (method === "GET" && !events.connected) root.online = false;
            if (done) done(xhr.status, response);
        }
        item.finish = finish;
        xhr.open(method, "http://127.0.0.1:17844/v1/" + path);
        xhr.setRequestHeader("Authorization", "Bearer " + Plasmoid.configuration.backendToken);
        if (method === "POST") xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function() { if (xhr.readyState === XMLHttpRequest.DONE) finish(); };
        root.requests = root.requests.concat([item]);
        xhr.send(data === null ? "" : JSON.stringify(data));
    }

    function readState() {
        if (root.reading) return;
        root.reading = true;
        root.request("GET", "state", null, function() { root.reading = false; });
    }

    function refresh() {
        root.request("POST", "reconnect", {}, function() { root.readState(); });
    }

    function selectDevice(id) {
        root.errorText = "";
        root.commandQueue = [];
        root.selectionSynced = true;
        root.request("POST", "select", {device: id}, function(status, response) {
            if (status !== 200) { root.commandQueue = []; root.showError(response.error || "The speakers did not respond. Try again."); }
        });
    }

    function showError(message) {
        root.errorText = L10n.tr(Qt.locale(), message);
        dismissError.restart();
    }

    function send(action, value) {
        if (!root.selectedId || (!root.available && action !== "sleep")) return;
        var job = {device: root.selectedId, action: action, value: value};
        var queue = root.commandQueue.slice();
        var last = queue.length ? queue[queue.length - 1] : null;
        if (last && last.device === job.device && last.action === action && ["volume", "seek", "volume_delta"].includes(action)) {
            if (action === "volume_delta") job.value = Math.max(-10, Math.min(10, Number(last.value) + Number(value)));
            queue[queue.length - 1] = job;
        } else if (queue.length < 8) queue.push(job);
        root.commandQueue = queue;
        root.runNextCommand();
    }

    function runNextCommand() {
        if (root.commandRunning || !root.commandQueue.length) return;
        var queue = root.commandQueue.slice();
        var job = queue.shift();
        root.commandQueue = queue;
        root.commandRunning = true;
        root.errorText = "";
        root.request("POST", "command", job, function(status, response) {
            root.commandRunning = false;
            if (status !== 200) { root.commandQueue = []; root.showError(response.error || "The speakers did not respond. Try again."); }
            root.runNextCommand();
        });
    }

    EventConnection {
        id: events
        token: Plasmoid.configuration.backendToken
        onSnapshot: function(data) { root.applySnapshot(data); }
        onRaiseRequested: root.expanded = true
        onConnectedChanged: if (!connected) root.readState()
    }
    Timer {
        interval: root.online ? 30000 : 5000
        running: !events.connected
        repeat: true
        triggeredOnStart: true
        onTriggered: root.readState()
    }
    Timer {
        interval: 1000
        running: root.expanded && (root.playing || root.sleepRemaining > 0)
        repeat: true
        onTriggered: root.displayClock = Date.now()
    }
    Timer {
        interval: 250
        running: root.requests.length > 0
        repeat: true
        onTriggered: {
            var expired = root.requests.filter(r => r.deadline <= Date.now());
            for (var item of expired) { item.xhr.abort(); item.finish(); }
        }
    }
    Timer { id: dismissError; interval: 10000; onTriggered: root.errorText = "" }
    onExpandedChanged: function(value) {
        if (value) { root.displayClock = Date.now(); if (!events.connected) root.readState(); }
    }
    Component.onDestruction: {
        root.closing = true;
        for (var item of root.requests) item.xhr.abort();
    }

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
