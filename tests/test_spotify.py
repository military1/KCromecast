import hashlib
import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs

from kcromecast.spotify import SpotifyConnect


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.client = SpotifyConnect(Path(temporary.name), Mock(), Mock())
        self.addCleanup(self.client.stop)
        self.client_id = "a" * 32

    def authorize(self):
        url = self.client.authorize(self.client_id, "ru")
        return parse_qs(urlsplit(url).query)

    def test_pkce_url_has_matching_challenge_and_minimal_scopes(self):
        query = self.authorize()
        digest = hashlib.sha256(self.client.pending["verifier"].encode()).digest()
        self.assertEqual(query["code_challenge"], [base64.urlsafe_b64encode(digest).decode().rstrip("=")])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:17844/spotify/callback"])
        self.assertNotIn("client_secret", query)
        self.assertEqual(set(query["scope"][0].split()), {"user-read-playback-state", "user-modify-playback-state"})

    @patch("kcromecast.spotify.requests.Session.post")
    def test_callback_is_single_use_and_secrets_stay_out_of_state(self, post):
        query = self.authorize()
        post.return_value.json.return_value = {"access_token": "secret-access", "refresh_token": "secret-refresh", "expires_in": 3600}
        callback = {"state": query["state"], "code": ["code"]}
        self.assertEqual(self.client.callback(callback), "ru")
        self.assertTrue(self.client.public_state()["connected"])
        self.assertNotIn("secret-", json.dumps(self.client.public_state()))
        self.assertEqual(self.client.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.client.callback(callback)
        self.assertEqual(post.call_count, 1)

    @patch("kcromecast.spotify.requests.Session.post")
    def test_invalid_oauth_state_never_exchanges_code(self, post):
        self.authorize()
        with self.assertRaises(ValueError):
            self.client.callback({"state": ["wrong"], "code": ["code"]})
        post.assert_not_called()

    @patch("kcromecast.spotify.requests.Session.post")
    def test_refresh_retains_refresh_token_when_not_rotated(self, post):
        self.client.credentials = {"client_id": self.client_id, "refresh_token": "refresh", "expires_at": 0}
        post.return_value.json.return_value = {"access_token": "new", "expires_in": 3600}
        self.assertEqual(self.client._access_token(), "new")
        self.assertEqual(self.client.credentials["refresh_token"], "refresh")

    @patch("kcromecast.spotify.requests.Session.request")
    def test_rate_limit_is_respected_without_immediate_retry(self, request):
        self.client.credentials = {"client_id": self.client_id, "refresh_token": "refresh", "access_token": "access", "expires_at": time.time() + 3600}
        request.return_value.status_code = 429
        request.return_value.headers = {"Retry-After": "60"}
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "Spotify is busy"):
                self.client.api("GET", "me/player")
        self.assertEqual(request.call_count, 1)

    def test_disconnect_clears_tokens_and_devices(self):
        self.client.credentials = {"client_id": self.client_id, "access_token": "secret", "refresh_token": "secret"}
        self.client.devices = [{"id": "device"}]
        self.client.disconnect()
        self.assertFalse(self.client.public_state()["connected"])
        self.assertEqual(self.client.devices_snapshot(), [])
        self.assertNotIn("secret", self.client.path.read_text())

    @patch("kcromecast.spotify.requests.Session.post")
    def test_revoked_refresh_token_removes_cached_devices(self, post):
        self.client.credentials = {"client_id": self.client_id, "refresh_token": "revoked", "expires_at": 0}
        self.client.devices = [{"id": "speaker", "name": "Speaker"}]
        post.return_value.status_code = 400
        with self.assertRaisesRegex(ValueError, "sign-in expired"):
            self.client._access_token()
        self.assertFalse(self.client.public_state()["connected"])
        self.assertEqual(self.client.devices_snapshot(), [])

    @patch("kcromecast.spotify.requests.Session.request")
    def test_nonobject_api_response_returns_a_readable_error(self, request):
        self.client.credentials = {"client_id": self.client_id, "refresh_token": "refresh", "access_token": "access", "expires_at": time.time() + 3600}
        request.return_value.status_code = 200
        request.return_value.json.return_value = []
        with self.assertRaisesRegex(ValueError, "Spotify did not respond"):
            self.client.api("GET", "me/player")

    @patch("kcromecast.spotify.requests.Session.request")
    def test_developer_quota_exhaustion_uses_long_backoff(self, request):
        self.client.credentials = {"client_id": self.client_id, "refresh_token": "refresh", "access_token": "access", "expires_at": time.time() + 3600}
        request.return_value.status_code = 429
        request.return_value.headers = {}
        request.return_value.json.return_value = {"reason": "QUOTA_EXCEEDED"}
        with self.assertRaisesRegex(ValueError, "quota is exhausted"):
            self.client.api("GET", "me/player")
        self.assertGreater(self.client.retry_at - time.monotonic(), 3590)

    def test_restricted_device_and_unavailable_volume_are_exposed(self):
        self.client.devices = [{"id": "tv", "name": "TV", "is_restricted": True},
                               {"id": "phone", "name": "Phone", "volume_percent": None}]
        devices = self.client.devices_snapshot()
        self.assertFalse(devices[0]["connected"])
        self.assertFalse(devices[1]["can_volume"])
        with self.assertRaises(ValueError):
            self.client.command("spotify:tv", "play")

    @patch.object(SpotifyConnect, "api")
    def test_idle_target_uses_transfer_playback(self, api):
        self.client.devices = [{"id": "speaker", "name": "Speaker", "volume_percent": 20}]
        self.client.command("spotify:speaker", "play")
        api.assert_called_once_with("PUT", "me/player", json={"device_ids": ["speaker"], "play": True})
