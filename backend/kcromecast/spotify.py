"""Optional Spotify Connect: PKCE login and the official Spotify Web API."""
import base64
import hashlib
import math
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlencode, unquote, urlsplit

import requests

from .storage import read_json, write_json

SCOPES = "user-read-playback-state user-modify-playback-state"


class SpotifyConnect:
    def __init__(self, directory, changed, artwork, port=17844):
        self.path = directory / "spotify.json"
        self.changed, self.artwork, self.port = changed, artwork, port
        self.lock = threading.RLock()
        self.api_lock = threading.RLock()
        self.http = requests.Session()
        self.wake_event = threading.Event()
        self.credentials = read_json(self.path)
        self.pending = None
        self.devices, self.playback = [], {}
        self.artwork_files = {}
        self.sampled_at = time.monotonic()
        self.error = ""
        self.retry_at = 0
        self.retry_message = "Spotify is busy. Try again later."
        self.closed = False
        self.thread = threading.Thread(target=self._run, name="spotify", daemon=True)

    @property
    def redirect_uri(self):
        return f"http://127.0.0.1:{self.port}/spotify/callback"

    def public_state(self):
        with self.lock:
            return {"connected": bool(self.credentials.get("refresh_token")),
                    "client_id": self.credentials.get("client_id", ""),
                    "redirect_uri": self.redirect_uri, "error": self.error}

    def authorize(self, client_id, language="en"):
        if not isinstance(client_id, str) or len(client_id) != 32 or any(c not in "0123456789abcdefABCDEF" for c in client_id):
            raise ValueError("Enter a valid Spotify Client ID.")
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        with self.lock:
            self.pending = {"state": state, "verifier": verifier, "client_id": client_id,
                            "expires": time.monotonic() + 600, "language": "ru" if language == "ru" else "en"}
            if not self.credentials.get("refresh_token"):
                self.credentials = {"client_id": client_id}
                write_json(self.path, self.credentials)
        self.changed()
        return "https://accounts.spotify.com/authorize?" + urlencode({
            "client_id": client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
            "scope": SCOPES, "state": state, "code_challenge_method": "S256", "code_challenge": challenge})

    def callback(self, query):
        with self.lock:
            pending = self.pending
            state = query.get("state", [""])[0]
            if not pending or time.monotonic() > pending["expires"] or not secrets.compare_digest(state, pending["state"]):
                raise ValueError("Spotify sign-in expired. Try again.")
            self.pending = None  # A callback is single-use, including a denial.
        if query.get("error") or not query.get("code"):
            raise ValueError("Spotify sign-in was cancelled.")
        with self.api_lock:
            try:
                response = self.http.post("https://accounts.spotify.com/api/token", data={
                    "grant_type": "authorization_code", "code": query["code"][0],
                    "client_id": pending["client_id"], "code_verifier": pending["verifier"],
                    "redirect_uri": self.redirect_uri}, timeout=10)
                response.raise_for_status()
                data = response.json()
                self._save_tokens(data, pending["client_id"])
            except (requests.RequestException, ValueError, KeyError):
                raise ValueError("Could not sign in to Spotify. Check the Client ID and redirect URI.") from None
        self.wake()
        self.changed()
        return pending["language"]

    def _save_tokens(self, data, client_id=None):
        if not data.get("access_token"):
            raise ValueError("Missing access token")
        with self.lock:
            credentials = dict(self.credentials)
            credentials.update(access_token=data["access_token"],
                               expires_at=time.time() + float(data.get("expires_in", 3600)))
            if client_id:
                credentials["client_id"] = client_id
                # A different authorization must never retain an old account's refresh token.
                credentials.pop("refresh_token", None)
            if data.get("refresh_token"):
                credentials["refresh_token"] = data["refresh_token"]
            write_json(self.path, credentials)
            self.credentials, self.error = credentials, ""

    def disconnect(self):
        # Serialize with refresh/callback so an in-flight response cannot re-save credentials.
        with self.api_lock:
            with self.lock:
                client_id = self.credentials.get("client_id", "")
                self.credentials = {"client_id": client_id}
                self.pending, self.devices, self.playback, self.error = None, [], {}, ""
                write_json(self.path, self.credentials)
        self.wake()
        self.changed()

    def _access_token(self):
        with self.lock:
            credentials = dict(self.credentials)
        if not credentials.get("refresh_token"):
            raise ValueError("Connect your Spotify account first.")
        if credentials.get("expires_at", 0) > time.time() + 45:
            return credentials["access_token"]
        response = self.http.post("https://accounts.spotify.com/api/token", data={
            "grant_type": "refresh_token", "refresh_token": credentials["refresh_token"],
            "client_id": credentials["client_id"]}, timeout=10)
        if response.status_code in (400, 401):
            with self.lock:
                self.credentials = {"client_id": credentials["client_id"]}
                self.devices, self.playback = [], {}
                self.error = "Spotify sign-in expired. Try again."
                write_json(self.path, self.credentials)
            self.changed()
            raise ValueError("Spotify sign-in expired. Try again.")
        response.raise_for_status()
        self._save_tokens(response.json())
        return self.credentials["access_token"]

    def api(self, method, endpoint, **kwargs):
        with self.api_lock:
            if time.monotonic() < self.retry_at:
                raise ValueError(self.retry_message)
            for attempt in range(2):
                token = self._access_token()
                response = self.http.request(method, "https://api.spotify.com/v1/" + endpoint,
                                            headers={"Authorization": "Bearer " + token}, timeout=10, **kwargs)
                if response.status_code == 401 and attempt == 0:
                    with self.lock:
                        self.credentials["expires_at"] = 0
                    continue
                if response.status_code == 429:
                    try:
                        body = response.json()
                        nested = body.get("error") if isinstance(body, dict) else None
                        reason = body.get("reason") if isinstance(body, dict) else None
                        if not reason and isinstance(nested, dict):
                            reason = nested.get("reason")
                    except ValueError:
                        reason = None
                    quota = reason == "QUOTA_EXCEEDED"
                    try:
                        wait = min(86400, max(3600 if quota else 5, int(response.headers.get("Retry-After", 3600 if quota else 30))))
                    except ValueError:
                        wait = 3600 if quota else 30
                    self.retry_at = time.monotonic() + wait
                    self.retry_message = "Spotify API quota is exhausted. Try again later." if quota else "Spotify is busy. Try again later."
                    raise ValueError(self.retry_message)
                if response.status_code == 403:
                    raise ValueError("Spotify requires Premium and permission to control this device.")
                if response.status_code == 404:
                    raise ValueError("Open Spotify on the target device first.")
                if response.status_code >= 400:
                    raise ValueError("Spotify did not respond. Try again.")
                if response.status_code == 204 or not response.content:
                    return {}
                try:
                    data = response.json()
                except ValueError:
                    raise ValueError("Spotify did not respond. Try again.") from None
                if not isinstance(data, dict):
                    raise ValueError("Spotify did not respond. Try again.")
                return data
        raise ValueError("Spotify sign-in expired. Try again.")

    def refresh(self):
        # Keep the credential generation stable through publication/disconnect.
        with self.api_lock:
            devices = self.api("GET", "me/player/devices").get("devices", [])
            playback = self.api("GET", "me/player")
            item = playback.get("item") or {}
            images = (item.get("album") or {}).get("images") or item.get("images") or []
            url = next((image.get("url", "") for image in images if image.get("url", "").startswith("https://")), "")
            with self.lock:
                self.devices, self.playback = devices, playback
                self.sampled_at, self.error = time.monotonic(), ""
            with self.lock:
                cached = self.artwork_files.get(url)
            if url and (not cached or not Path(unquote(urlsplit(cached).path)).is_file()):
                self.artwork.request(url)
        self.changed()

    def artwork_ready(self, url, path):
        with self.lock:
            if len(self.artwork_files) >= 32:
                self.artwork_files.pop(next(iter(self.artwork_files)))
            self.artwork_files[url] = path

    def devices_snapshot(self):
        with self.lock:
            playback, sampled_at = self.playback, self.sampled_at
            active = playback.get("device", {}).get("id")
            result = []
            for device in self.devices:
                if not device.get("id"):
                    continue
                current = device["id"] == active
                item = (playback.get("item") or {}) if current else {}
                album = item.get("album") or {}
                images = album.get("images") or item.get("images") or []
                artwork = next((self.artwork_files.get(image.get("url"), "") for image in images
                                if image.get("url") in self.artwork_files), "")
                playing = current and bool(playback.get("is_playing"))
                duration = max(0, (item.get("duration_ms") or 0) / 1000)
                position = (playback.get("progress_ms") or 0) / 1000 if current else 0
                if playing:
                    position += time.monotonic() - sampled_at
                restrictions = (playback.get("actions") or {}).get("disallows", {}) if current else {}
                allowed = not device.get("is_restricted") and not self.error
                volume = device.get("volume_percent")
                result.append({"id": "spotify:" + device["id"], "name": device.get("name") or "Spotify",
                    "model": device.get("type", ""), "group": False, "transport": "spotify",
                    "connected": allowed, "connection": "CONNECTED" if allowed else "RESTRICTED",
                    "state": "PLAYING" if playing else "PAUSED" if current and item else "IDLE",
                    "title": item.get("name", ""), "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])),
                    "album": album.get("name", ""), "duration": duration, "position": min(position, duration) if duration else 0,
                    "can_pause": allowed and not restrictions.get("pausing", False),
                    "can_seek": allowed and current and duration > 0 and not restrictions.get("seeking", False),
                    "can_next": allowed and current and not restrictions.get("skipping_next", False),
                    "can_previous": allowed and current and not restrictions.get("skipping_prev", False),
                    "can_volume": allowed and volume is not None and device.get("supports_volume", True),
                    "volume": volume or 0, "muted": False, "app": "Spotify Connect", "service": "spotify",
                    "artwork": artwork})
            return result

    def command(self, key, action, value=None):
        with self.api_lock:
            raw_id = key.removeprefix("spotify:")
            device = next((d for d in self.devices_snapshot() if d["id"] == key and d["connected"]), None)
            if not device:
                raise ValueError("The speakers are unavailable. Check your network connection.")
            params = {"device_id": raw_id}
            if action == "toggle":
                action = "pause" if device["state"] == "PLAYING" else "play"
            if action == "play" and device["state"] == "IDLE":
                self.api("PUT", "me/player", json={"device_ids": [raw_id], "play": True})
            elif action in ("play", "pause", "stop"):
                self.api("PUT", "me/player/" + ("pause" if action == "stop" else action), params=params)
            elif action in ("next", "previous"):
                if not device["can_" + action]:
                    raise ValueError("No track is available in this queue.")
                self.api("POST", "me/player/" + action, params=params)
            elif action == "seek":
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    value = -1
                if not device["can_seek"] or not math.isfinite(value) or not 0 <= value <= device["duration"]:
                    raise ValueError("Invalid playback position")
                self.api("PUT", "me/player/seek", params={**params, "position_ms": round(value * 1000)})
            elif action in ("volume", "volume_delta"):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    value = float("nan")
                if not math.isfinite(value) or not device["can_volume"]:
                    raise ValueError("Invalid volume")
                if action == "volume_delta":
                    if not -10 <= value <= 10:
                        raise ValueError("Invalid volume change")
                    value = max(0, min(100, device["volume"] + value))
                if not 0 <= value <= 100:
                    raise ValueError("Invalid volume")
                self.api("PUT", "me/player/volume", params={**params, "volume_percent": round(value)})
                with self.lock:
                    for target in self.devices:
                        if target.get("id") == raw_id:
                            target["volume_percent"] = round(value)
            else:
                raise ValueError("Unknown command")
            self.changed()
            self.wake()

    def start(self):
        self.thread.start()

    def wake(self):
        self.wake_event.set()

    def _run(self):
        try:
            while not self.closed:
                self.wake_event.clear()
                with self.lock:
                    connected = bool(self.credentials.get("refresh_token"))
                delay = None
                if connected:
                    try:
                        self.refresh()
                        delay = 5 if self.playback.get("is_playing") else 15
                    except (requests.RequestException, ValueError, KeyError) as error:
                        with self.lock:
                            self.error = str(error) if isinstance(error, ValueError) and not isinstance(error, requests.RequestException) else "Spotify did not respond. Try again."
                        self.changed()
                        delay = max(15, self.retry_at - time.monotonic())
                if not self.closed:
                    self.wake_event.wait(delay)
        finally:
            self.http.close()

    def stop(self):
        self.closed = True
        self.wake()
        if self.thread.is_alive():
            self.thread.join(timeout=1)
        elif self.thread.ident is None:
            self.http.close()
