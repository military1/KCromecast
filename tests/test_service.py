"""Behavior checks for receiver control, state and loopback authentication."""
import json
import threading
import time
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
from http.server import ThreadingHTTPServer

from pychromecast.controllers.media import MediaStatus
from kcromecast.service import Device, Handler, Manager, StatusListener, media_snapshot, service_name


def manager_with_device(state="PLAYING"):
    temporary = tempfile.TemporaryDirectory(prefix="kcromecast-test-")
    manager = Manager(Path(temporary.name), network=False, cache_dir=Path(temporary.name) / "artwork")
    manager.temporary = temporary
    status = MediaStatus()
    status.player_state = state
    status.duration = 200
    status.current_time = 25
    status.supported_media_commands = 1 | 2 | 64
    status.media_metadata = {"title": "Track", "artist": "Artist", "images": [
        {"url": "http://untrusted/image", "width": 2000},
        {"url": "https://example.com/cover.jpg", "width": 500}]}
    cast = Mock()
    cast.media_controller.status = status
    cast.status.volume_level, cast.status.volume_muted = .18, False
    device = Device("group", "Speakers", "Cast Group", True, cast, True, media_snapshot(status))
    manager.devices = {"group": device}
    return manager, cast, status


class ManagerTestCase(unittest.TestCase):
    def make_manager(self, state="PLAYING"):
        manager, cast, status = manager_with_device(state)
        self.addCleanup(manager.temporary.cleanup)
        self.addCleanup(manager.stop)
        return manager, cast, status


class ReceiverTests(ManagerTestCase):
    def test_recovery_completes_when_old_disconnect_reports_join_timeout(self):
        manager, cast, _ = self.make_manager()
        manager.browser, manager.zc = Mock(), Mock()
        old_browser, old_zc = manager.browser, manager.zc
        cast.disconnect.side_effect = TimeoutError("join", 0)
        with patch("kcromecast.service.Zeroconf") as zeroconf, patch("kcromecast.service.CastBrowser") as browser:
            manager._recover()
            old_browser.stop_discovery.assert_called_once()
            old_zc.close.assert_called_once()
            browser.return_value.start_discovery.assert_called_once()
            self.assertIs(manager.zc, zeroconf.return_value)
            self.assertFalse(manager.recovering)

    def test_a_stale_network_connection_cannot_replace_the_current_device(self):
        manager, cast, _ = self.make_manager()
        old_device = manager.devices["group"]
        info = Mock(uuid="group", friendly_name="Group", model_name="Cast")
        with patch("kcromecast.service.pychromecast.get_chromecast_from_cast_info") as get_cast:
            get_cast.return_value.disconnect.side_effect = TimeoutError("join", 0)
            manager.connect(info, -1, None)
            self.assertIs(manager.devices["group"], old_device)
            get_cast.return_value.start.assert_not_called()

    def test_unusual_artwork_metadata_does_not_break_receiver_updates(self):
        _, _, status = self.make_manager()
        for images in [None, "invalid", [None, "invalid", {"url": None}], [{"url": "https://example.com/cover.jpg"}]]:
            status.media_metadata = {"title": "Still works", "images": images}
            self.assertEqual(media_snapshot(status)["title"], "Still works")

    def test_spotify_cast_session_recognizes_source_and_album_metadata(self):
        manager, cast, status = self.make_manager()
        status.media_metadata = {"metadataType": 3, "title": "A Spotify track",
                                 "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
                                 "album": {"name": "Album"},
                                 "images": [{"url": "https://i.scdn.co/image/cover", "width": 640}]}
        receiver = Mock(volume_level=.18, volume_muted=False, display_name="Spotify")
        StatusListener(manager, "group").new_cast_status(receiver)
        snapshot = media_snapshot(status)
        self.assertEqual(manager.snapshot()["devices"][0]["service"], "spotify")
        self.assertEqual(snapshot["artist"], "Artist A, Artist B")
        self.assertEqual(snapshot["album"], "Album")
        self.assertTrue(snapshot["can_next"])
        self.assertEqual(service_name("YouTube Music"), "youtube_music")

    def test_pause_and_resume_use_existing_session(self):
        manager, cast, status = self.make_manager()
        manager.command("group", "toggle")
        cast.media_controller.pause.assert_called_once()
        status.player_state = "PAUSED"
        manager.command("group", "toggle")
        cast.media_controller.play.assert_called_once()
        cast.start_app.assert_not_called()
        cast.media_controller.play_media.assert_not_called()

    def test_seek_preserves_paused_state(self):
        manager, cast, status = self.make_manager("PAUSED")
        manager.command("group", "seek", 42)
        cast.media_controller.seek.assert_called_once_with(42, timeout=8)
        cast.media_controller.pause.assert_called_once()

    def test_relative_volume_starts_from_actual_receiver_value(self):
        manager, cast, status = self.make_manager()
        manager.command("group", "volume_delta", 2)
        self.assertAlmostEqual(cast.set_volume.call_args.args[0], .20)

    def test_unsupported_previous_does_not_send_a_command(self):
        manager, cast, status = self.make_manager()
        with self.assertRaises(ValueError):
            manager.command("group", "previous")
        cast.media_controller.queue_prev.assert_not_called()

    def test_invalid_and_nonfinite_values_are_rejected(self):
        manager, cast, status = self.make_manager()
        for value in [101, -1, "invalid", float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                manager.command("group", "volume", value)
        cast.set_volume.assert_not_called()

    def test_sleep_timer_is_bound_to_selected_device_and_cancellable(self):
        manager, cast, status = self.make_manager()
        manager.command("group", "sleep", 15)
        snapshot = manager.snapshot()
        self.assertEqual(snapshot["sleep"]["device"], "group")
        self.assertGreater(snapshot["sleep"]["remaining"], 890)
        manager.command("group", "sleep", 0)
        self.assertEqual(manager.snapshot()["sleep"]["remaining"], 0)
        cast.media_controller.pause.assert_not_called()

    def test_expired_timer_pauses_once_and_clears_itself(self):
        manager, cast, status = self.make_manager()
        manager.sleep.data = {"device": "group", "deadline": time.time() - 1, "minutes": 1, "fade_seconds": 0}
        manager.sleep.start()
        try:
            deadline = time.monotonic() + 2
            while not cast.media_controller.pause.called and time.monotonic() < deadline:
                time.sleep(.02)
            cast.media_controller.pause.assert_called_once()
            self.assertEqual(manager.snapshot()["sleep"]["remaining"], 0)
            self.assertEqual(manager.sleep.snapshot()["device"], "")
        finally:
            manager.sleep.stop()

    def test_snapshot_does_not_expose_receiver_secrets_or_unsafe_artwork(self):
        manager, cast, status = self.make_manager()
        normalized = media_snapshot(status)
        self.assertEqual(normalized["artwork_remote"], "https://example.com/cover.jpg")
        self.assertNotIn("session_id", normalized)
        self.assertNotIn("content_id", normalized)

    def test_disconnected_receiver_rejects_commands(self):
        manager, cast, status = self.make_manager()
        manager.devices["group"].connected = False
        with self.assertRaises(ValueError):
            manager.command("group", "toggle")
        cast.media_controller.pause.assert_not_called()


class APITests(ManagerTestCase):
    def setUp(self):
        self.manager, _, _ = self.make_manager()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.manager, self.server.token = self.manager, "test-token"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_requests_require_authorization(self):
        with self.assertRaises(HTTPError) as error:
            self.opener.open(self.url + "/v1/state")
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        request = Request(self.url + "/v1/state", headers={"Authorization": "Bearer test-token"})
        with self.opener.open(request) as response:
            self.assertEqual(json.load(response)["devices"][0]["id"], "group")

    def test_browser_rebinding_host_is_rejected_even_with_token(self):
        request = Request(self.url + "/v1/state", headers={"Authorization": "Bearer test-token", "Host": "example.com"})
        with self.assertRaises(HTTPError) as error:
            self.opener.open(request)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_malformed_command_does_not_crash_service(self):
        request = Request(self.url + "/v1/command", data=b"[invalid", headers={"Authorization": "Bearer test-token"})
        with self.assertRaises(HTTPError) as error:
            self.opener.open(request)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
