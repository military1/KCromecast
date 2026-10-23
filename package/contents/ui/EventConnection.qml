import QtQuick
import QtWebSockets

Item {
    id: connection
    required property string token
    property url endpoint: "ws://127.0.0.1:17845/v1/events"
    property bool connected: false
    property bool enabledConnection: false
    property int retries: 0
    signal snapshot(var data)
    signal raiseRequested()

    function retry() {
        connection.connected = false;
        connection.enabledConnection = false;
        if (!reconnect.running && token.length > 0) reconnect.start();
    }

    WebSocket {
        id: socket
        url: connection.endpoint
        active: connection.enabledConnection && connection.token.length > 0
        onStatusChanged: function(status) {
            if (status === WebSocket.Open) {
                sendTextMessage(JSON.stringify({token: connection.token}));
            } else if (status === WebSocket.Error || status === WebSocket.Closed) {
                connection.retry();
            }
        }
        onTextMessageReceived: function(message) {
            try {
                var data = JSON.parse(message);
                if (data.event === "raise") { connection.raiseRequested(); return; }
                if (!data.instance || !Array.isArray(data.devices)) return;
                connection.connected = true;
                connection.retries = 0;
                reconnect.stop();
                connection.snapshot(data);
            } catch (error) {}
        }
    }
    Timer {
        id: reconnect
        interval: Math.min(30000, 500 * Math.pow(2, Math.min(connection.retries, 6)))
        onTriggered: { connection.retries++; connection.enabledConnection = true; }
    }
    onTokenChanged: {
        if (token.length > 0) { reconnect.stop(); enabledConnection = false; reconnect.start(); }
    }
    Component.onCompleted: enabledConnection = true
    Component.onDestruction: { reconnect.stop(); socket.active = false; }
}
