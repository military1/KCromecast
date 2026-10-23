"""End-to-end desktop checks, run inside an isolated D-Bus session."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from dbus_fast import Message, Variant
from dbus_fast.aio import MessageBus
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from kcromecast.desktop import DesktopRuntime
from kcromecast.service import Device, Manager, media_snapshot
from pychromecast.controllers.media import MediaStatus


class DesktopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.manager = Manager(temporary.name, network=False, cache_dir=Path(temporary.name) / "art")
        self.addCleanup(self.manager.stop)
        status = MediaStatus()
        status.player_state, status.duration, status.current_time = "PAUSED", 200, 25
        status.supported_media_commands = 1 | 2 | 64
        status.media_metadata = {"title": "Track", "artist": "Artist"}
        self.cast = Mock()
        self.cast.media_controller.status = status
        self.cast.status.volume_level, self.cast.status.volume_muted = .2, False
        device = Device("group", "Group", "Cast Group", True, self.cast, True, media_snapshot(status))
        device.receiver = {"volume": 20, "muted": False, "app": "YouTube Music"}
        self.manager.devices = {"group": device}
        self.manager.selected = "group"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.runtime = DesktopRuntime(self.manager, "test-token", port)
        self.runtime.start()
        self.addCleanup(self.runtime.stop)
        self.url = f"ws://127.0.0.1:{port}/v1/events"

    def test_authenticated_events_are_immediate_and_idle_stream_is_quiet(self):
        with connect(self.url, proxy=None) as client:
            client.send(json.dumps({"token": "test-token"}))
            initial = json.loads(client.recv(timeout=2))
            self.assertEqual(initial["devices"][0]["title"], "Track")
            # Initial MPRIS publication may coincide with connection establishment.
            try:
                client.recv(timeout=.15)
            except TimeoutError:
                pass
            self.manager.devices["group"].media["title"] = "New track"
            self.manager.changed()
            changed = json.loads(client.recv(timeout=2))
            self.assertEqual(changed["devices"][0]["title"], "New track")
            with self.assertRaises(TimeoutError):
                client.recv(timeout=.2)

    def test_wrong_token_and_browser_origin_are_rejected(self):
        with connect(self.url, proxy=None) as client:
            client.send(json.dumps({"token": "wrong"}))
            with self.assertRaises(ConnectionClosed):
                client.recv(timeout=2)
        with self.assertRaises(InvalidStatus):
            connect(self.url, proxy=None, origin="https://example.com")

    @unittest.skipUnless(shutil.which("qml6"), "Qt 6 QML runtime is not installed")
    def test_real_qt_websocket_client_authenticates_and_receives_state(self):
        self.runtime.loop.call_soon_threadsafe(self.runtime.raise_player)
        module = (Path(__file__).resolve().parents[1] / "package/contents/ui").as_uri()
        source = f'''import QtQuick
import "{module}"
EventConnection {{
    token: "test-token"
    endpoint: "{self.url}"
    onSnapshot: function(data) {{ console.log("KCEVENT", data.devices[0].title); }}
    onRaiseRequested: {{ console.log("KCRAISE"); Qt.quit(); }}
    Timer {{ interval: 5000; running: true; onTriggered: Qt.exit(9) }}
}}
'''
        path = self.manager.state_dir / "events.qml"
        path.write_text(source)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
        result = subprocess.run([shutil.which("qml6"), str(path)], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("KCEVENT Track", result.stderr)
        self.assertIn("KCRAISE", result.stderr)

    def test_mpris_metadata_commands_and_stale_track_protection(self):
        async def check():
            bus = await MessageBus().connect()
            try:
                name, path = "org.mpris.MediaPlayer2.kcromecast", "/org/mpris/MediaPlayer2"
                introspection = await bus.introspect(name, path)
                proxy = bus.get_proxy_object(name, path, introspection)
                player = proxy.get_interface("org.mpris.MediaPlayer2.Player")
                properties = proxy.get_interface("org.freedesktop.DBus.Properties")
                metadata = await player.get_metadata()
                self.assertEqual(metadata["xesam:title"].value, "Track")
                self.assertEqual(await player.get_playback_status(), "Paused")
                await player.call_play_pause()
                self.cast.media_controller.play.assert_called_once()
                await player.call_set_position("/org/kcromecast/track/stale", 42_000_000)
                self.cast.media_controller.seek.assert_not_called()
                await player.call_set_position(metadata["mpris:trackid"].value, 42_000_000)
                self.cast.media_controller.seek.assert_called_once_with(42, timeout=8)
                await properties.call_set("org.mpris.MediaPlayer2.Player", "Volume", Variant("d", .24))
                self.cast.set_volume.assert_called_once_with(.24, timeout=8)
            finally:
                bus.disconnect()
        asyncio.run(check())

    def test_resume_and_connected_network_trigger_recovery(self):
        self.manager.reconnect = Mock()
        signal = Message.new_signal("/org/freedesktop/login1", "org.freedesktop.login1.Manager", "PrepareForSleep", "b", [True])
        self.runtime._system_signal(signal)
        self.manager.reconnect.assert_not_called()
        signal.body = [False]
        self.runtime._system_signal(signal)
        self.manager.reconnect.assert_called_once()
        signal = Message.new_signal("/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager", "StateChanged", "u", [70])
        self.runtime._system_signal(signal)
        self.assertEqual(self.manager.reconnect.call_count, 2)


if __name__ == "__main__":
    unittest.main()
