"""Persistent Cast connections and an authenticated, loopback-only UI API.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import json
import logging
import math
from pathlib import Path
import secrets
import signal
import threading
import time

import pychromecast
from pychromecast.discovery import AbstractCastListener, CastBrowser
from zeroconf import Zeroconf

from . import __version__
from .artwork import ArtworkCache
from .sleep import SleepTimer
from .storage import read_json, write_json
from .paths import CONFIG_DIR, CACHE_DIR

LOG = logging.getLogger("kcromecast")
CONFIG = CONFIG_DIR / "service.json"
CACHE = CACHE_DIR / "artwork"
ACTIVE = {"PLAYING", "PAUSED", "BUFFERING"}


def disconnect_cast(cast):
    # PyChromecast's zero-timeout disconnect signals the thread correctly, then
    # join(0) raises while it is still exiting. This is normal asynchronous close.
    try:
        cast.disconnect(timeout=0)
    except (TimeoutError, RuntimeError):
        pass


def service_name(app):
    name = str(app or "").casefold()
    if "spotify" in name:
        return "spotify"
    if "youtube" in name:
        return "youtube_music" if "music" in name else "youtube"
    return "cast"


def metadata_text(value):
    if isinstance(value, list):
        return ", ".join(filter(None, (metadata_text(item) for item in value)))
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def finite(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def artwork_url(images):
    if not isinstance(images, list):
        return ""
    candidates = sorted((image for image in images if isinstance(image, dict)),
                        key=lambda image: finite(image.get("width")), reverse=True)
    for image in candidates:
        url = image.get("url")
        if not isinstance(url, str):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
                return url
        except ValueError:
            continue
    return ""


def media_snapshot(status):
    """Normalize receiver data; never expose media URLs, tokens or session IDs."""
    metadata = status.media_metadata if isinstance(status.media_metadata, dict) else {}
    artwork = artwork_url(metadata.get("images"))
    state = status.player_state
    duration = max(0, finite(status.duration))
    position = max(0, finite(status.adjusted_current_time))
    return {
        "state": state if state in ACTIVE else "IDLE",
        "title": metadata_text(metadata.get("title")),
        "artist": metadata_text(metadata.get("artist") or metadata.get("artists") or metadata.get("albumArtist")),
        "album": metadata_text(metadata.get("albumName") or metadata.get("album")),
        "duration": duration,
        "position": min(position, duration) if duration else position,
        "can_pause": bool(status.supports_pause),
        "can_seek": bool(status.supports_seek and duration > 0),
        "can_next": bool(status.supports_queue_next),
        "can_previous": bool(status.supports_queue_prev),
        "artwork_remote": artwork,
    }


@dataclass
class Device:
    id: str
    name: str
    model: str
    group: bool
    cast: object = None
    connected: bool = False
    media: dict = field(default_factory=lambda: {"state": "IDLE"})
    receiver: dict = field(default_factory=lambda: {"volume": 0, "muted": False, "app": ""})
    updated: float = field(default_factory=time.monotonic)
    artwork: str = ""
    artwork_remote: str = ""
    connection: str = "CONNECTING"
    command_lock: threading.Lock = field(default_factory=threading.Lock)


class StatusListener:
    def __init__(self, manager, device_id, cast=None):
        self.manager, self.device_id, self.cast = manager, device_id, cast

    def device(self):
        device = self.manager.devices.get(self.device_id)
        return device if device and (self.cast is None or device.cast is self.cast) else None

    def new_media_status(self, status):
        if self.device():
            self.manager.update_media(self.device_id, status, self.cast)

    def load_media_failed(self, queue_item_id, error_code):
        LOG.info("Receiver reported a media error: %s", error_code)

    def new_cast_status(self, status):
        with self.manager.lock:
            device = self.device()
            if device:
                device.receiver = {
                    "volume": round(max(0, min(1, finite(status.volume_level))) * 100),
                    "muted": bool(status.volume_muted),
                    "app": str(status.display_name or ""),
                    "service": service_name(status.display_name),
                }
        self.manager.changed()

    def new_connection_status(self, status):
        with self.manager.lock:
            device = self.device()
            if device:
                device.connected = status.status == "CONNECTED"
                device.connection = str(status.status)
        self.manager.changed()
        self.manager.sleep.wake()


class DiscoveryListener(AbstractCastListener):
    def __init__(self, manager):
        self.manager = manager

    def add_cast(self, uuid, service):
        self.manager.discover(uuid)

    def update_cast(self, uuid, service):
        self.manager.discover(uuid)

    def remove_cast(self, uuid, service, cast_info):
        # Group leader changes must not delete a group's identity/session.
        pass


class Manager:
    def __init__(self, state_dir=None, network=True, cache_dir=None):
        self.lock = threading.RLock()
        self.discovery_lock = threading.Lock()
        self.devices = {}
        self.connecting = {}
        self.network_generation = 0
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cast")
        self.stopping = threading.Event()
        self.listeners = set()
        self.revision = 0
        self.instance = secrets.token_hex(8)
        self.error = ""
        self.state_dir = Path(state_dir or CONFIG.parent)
        self.selected = str(read_json(self.state_dir / "selection.json").get("device", ""))
        self.sleep = SleepTimer(self.state_dir / "sleep.json", self.device_snapshot,
                               lambda key, action, value: self.command(key, action, value, origin="timer"), self.changed)
        self.artwork = ArtworkCache(cache_dir or CACHE, self.artwork_ready, self.protected_artwork)
        self.spotify = None
        self.zc = Zeroconf() if network else None
        self.browser = CastBrowser(DiscoveryListener(self), self.zc) if network else None
        self.recovering = False

    def subscribe(self, callback):
        with self.lock:
            self.listeners.add(callback)

    def unsubscribe(self, callback):
        with self.lock:
            self.listeners.discard(callback)

    def changed(self, error=None):
        with self.lock:
            if error:
                self.error = error
            self.revision += 1
            callbacks = tuple(self.listeners)
        for callback in callbacks:
            try:
                callback()
            except Exception:
                LOG.debug("State subscriber failed", exc_info=True)

    def start(self):
        if self.browser:
            self.browser.start_discovery()
        self.sleep.start()
        if self.spotify:
            self.spotify.start()

    def discover(self, uuid):
        key = str(uuid)
        info = self.browser.devices.get(uuid) if self.browser else None
        if not info:
            return
        with self.lock:
            existing = self.devices.get(key)
            if existing:
                renamed = existing.name != (info.friendly_name or "Chromecast")
                existing.name = info.friendly_name or "Chromecast"
                if existing.cast.socket_client.is_alive() and not existing.cast.socket_client.stop.is_set():
                    if renamed:
                        self.changed()
                    return
            if key in self.connecting or self.stopping.is_set():
                return
            generation, zc = self.network_generation, self.zc
            self.connecting[key] = generation
        self.pool.submit(self.connect, info, generation, zc)

    def connect(self, info, generation, zc):
        key, cast = str(info.uuid), None
        try:
            cast = pychromecast.get_chromecast_from_cast_info(info, zc, timeout=6, retry_wait=3)
            device = Device(key, info.friendly_name or "Chromecast", info.model_name or "",
                            cast.cast_type == "group", cast)
            with self.lock:
                if generation != self.network_generation or self.stopping.is_set():
                    disconnect_cast(cast)
                    return
                old = self.devices.get(key)
                self.devices[key] = device
            if old:
                disconnect_cast(old.cast)
            listener = StatusListener(self, key, cast)
            cast.register_status_listener(listener)
            cast.register_connection_listener(listener)
            cast.media_controller.register_status_listener(listener)
            cast.start()
            self.changed()
        except Exception:
            LOG.debug("Could not connect to a Cast receiver", exc_info=True)
            if cast:
                disconnect_cast(cast)
        finally:
            with self.lock:
                if self.connecting.get(key) == generation:
                    self.connecting.pop(key, None)

    def reconnect(self):
        self.sleep.wake()
        if self.spotify:
            self.spotify.wake()
        with self.lock:
            if self.recovering or self.stopping.is_set() or not self.browser:
                return
            self.recovering = True
        self.pool.submit(self._recover)

    def _recover(self):
        try:
            with self.discovery_lock:
                if self.stopping.is_set():
                    return
                self.browser.stop_discovery()
                with self.lock:
                    self.network_generation += 1
                    self.connecting.clear()
                    devices = list(self.devices.values())
                for device in devices:
                    disconnect_cast(device.cast)
                    with self.lock:
                        device.connected, device.connection = False, "CONNECTING"
                old_zc = self.zc
                # Zeroconf sockets belong to the old interface addresses. Both
                # discovery and Cast connections must use a fresh instance.
                self.zc = Zeroconf()
                self.browser = CastBrowser(DiscoveryListener(self), self.zc)
                self.browser.start_discovery()
                old_zc.close()
        except Exception:
            LOG.debug("Discovery recovery failed", exc_info=True)
        finally:
            with self.lock:
                self.recovering = False
            self.changed()

    def update_media(self, key, status, cast=None):
        snapshot = media_snapshot(status)
        url = snapshot.pop("artwork_remote")
        with self.lock:
            device = self.devices.get(key)
            if not device or (cast is not None and device.cast is not cast):
                return
            device.media, device.updated = snapshot, time.monotonic()
            if device.artwork_remote != url:
                device.artwork_remote, device.artwork = url, ""
            needs_artwork = url and not device.artwork
        if needs_artwork:
            self.artwork.request(url)
        self.changed()

    def protected_artwork(self):
        with self.lock:
            protected = {device.artwork for device in self.devices.values() if device.artwork}
        if self.spotify:
            protected.update(device["artwork"] for device in self.spotify.devices_snapshot() if device.get("artwork"))
        return protected

    def artwork_ready(self, url, path):
        with self.lock:
            for device in self.devices.values():
                if device.artwork_remote == url:
                    device.artwork = path
        if self.spotify:
            self.spotify.artwork_ready(url, path)
        self.changed()

    def _cast_snapshots(self):
        now = time.monotonic()
        devices = []
        with self.lock:
            for device in self.devices.values():
                media = dict(device.media)
                if media.get("state") == "PLAYING" and device.connected:
                    media["position"] = media.get("position", 0) + now - device.updated
                    if media.get("duration"):
                        media["position"] = min(media["position"], media["duration"])
                devices.append({"id": device.id, "name": device.name, "model": device.model,
                                "group": device.group, "connected": device.connected, "connection": device.connection,
                                "transport": "cast", **media, **device.receiver, "artwork": device.artwork})
        return devices

    def device_snapshot(self, key):
        return next((device for device in self.all_devices() if device["id"] == key), None)

    def all_devices(self):
        devices = self._cast_snapshots()
        if self.spotify:
            devices.extend(self.spotify.devices_snapshot())
        devices.sort(key=lambda device: (not device.get("group", False), device["name"].casefold(), device["id"]))
        return devices

    def snapshot(self):
        with self.lock:
            devices = self.all_devices()
            if not self.selected and devices:
                selected = next((device for device in devices if device.get("group") and device.get("state") in ACTIVE),
                                next((device for device in devices if device.get("state") in ACTIVE), devices[0]))
                self.selected = selected["id"]
            selected, revision, error = self.selected, self.revision, self.error
            return {"version": __version__, "instance": self.instance, "revision": revision,
                    "sampled_at": time.monotonic(), "selected": selected,
                    "devices": devices, "sleep": self.sleep.snapshot(), "error": error,
                    "spotify": self.spotify.public_state() if self.spotify else {"connected": False}}

    def select(self, key):
        if not isinstance(key, str) or not self.device_snapshot(key):
            raise ValueError("The speakers are unavailable. Check your network connection.")
        with self.lock:
            self.selected, self.error = key, ""
            write_json(self.state_dir / "selection.json", {"device": key})
        self.changed()

    def command(self, key, action, value=None, origin="user"):
        if action == "sleep":
            settings = value if isinstance(value, dict) else {"minutes": value}
            cancelling = finite(settings.get("minutes"), -1) == 0
            if not self.device_snapshot(key) and not (cancelling and self.sleep.snapshot()["device"] == key):
                raise ValueError("The speakers are unavailable. Check your network connection.")
            self.sleep.set(key, settings.get("minutes"), settings.get("fade_seconds", 0))
            with self.lock:
                self.error = ""
            self.changed()
            return
        if origin != "timer" and action in ("volume", "volume_delta", "mute"):
            self.sleep.user_volume(key)
        if isinstance(key, str) and key.startswith("spotify:") and self.spotify:
            self.spotify.command(key, action, value)
            return
        with self.lock:
            device = self.devices.get(key)
            if not device or not device.connected:
                raise ValueError("The speakers are unavailable. Check your network connection.")
        with device.command_lock:
            media = device.cast.media_controller
            state = media_snapshot(media.status)
            if action in ("toggle", "play", "pause"):
                if state["state"] not in ACTIVE:
                    raise ValueError("Start music on your phone first.")
                pause = action == "pause" or (action == "toggle" and state["state"] in ("PLAYING", "BUFFERING"))
                if pause:
                    if not state["can_pause"]:
                        raise ValueError("This service does not support pausing.")
                    media.pause(timeout=8)
                else:
                    media.play(timeout=8)
            elif action in ("next", "previous"):
                if not state["can_" + action]:
                    raise ValueError("No track is available in this queue.")
                (media.queue_next if action == "next" else media.queue_prev)(timeout=8)
            elif action == "seek":
                if not state["can_seek"]:
                    raise ValueError("Seeking is unavailable for this stream.")
                position = finite(value, -1)
                if not 0 <= position <= state["duration"]:
                    raise ValueError("Invalid playback position")
                was_paused = state["state"] == "PAUSED"
                media.seek(position, timeout=8)
                if was_paused:
                    media.pause(timeout=8)
            elif action in ("volume", "volume_delta"):
                volume = finite(value, -1000)
                if action == "volume_delta":
                    if not -10 <= volume <= 10:
                        raise ValueError("Invalid volume change")
                    volume += finite(device.cast.status.volume_level) * 100
                elif not 0 <= volume <= 100:
                    raise ValueError("Invalid volume")
                device.cast.set_volume(max(0, min(100, volume)) / 100, timeout=8)
            elif action == "mute":
                device.cast.set_volume_muted(not device.cast.status.volume_muted, timeout=8)
            elif action == "stop":
                media.stop(timeout=8)
            else:
                raise ValueError("Unknown command")
            with self.lock:
                self.error = ""
        self.changed()

    def stop(self):
        self.stopping.set()
        self.sleep.stop()
        if self.spotify:
            self.spotify.stop()
        with self.discovery_lock:
            if self.browser:
                self.browser.stop_discovery()
        with self.lock:
            casts = [device.cast for device in self.devices.values()]
        for cast in casts:
            try:
                disconnect_cast(cast)
            except Exception:
                LOG.debug("Receiver disconnect failed", exc_info=True)
        if self.zc:
            self.zc.close()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.artwork.stop()


class LocalServer(ThreadingHTTPServer):
    """Bound request concurrency and prevent a stalled client from holding a worker."""
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(12)
        return connection, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "KCromecast/1"

    def log_message(self, *args):
        pass  # Never log authorization headers or media metadata.

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self):
        expected_host = f"127.0.0.1:{self.server.server_port}"
        auth = self.headers.get("Authorization", "")
        valid = (self.headers.get("Host") == expected_host and auth.isascii() and
                 secrets.compare_digest(auth, "Bearer " + self.server.token))
        if not valid:
            self.reply(403, {"error": "Unauthorized"})
        return valid

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/spotify/callback" and self.server.manager.spotify:
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.reply(403, {"error": "Unauthorized"})
                return
            language = "ru" if self.headers.get("Accept-Language", "").split(",")[0].lower().startswith("ru") else "en"
            try:
                language = self.server.manager.spotify.callback(parse_qs(parsed.query))
                text = "Spotify подключён. Можно закрыть эту вкладку и вернуться к KCromecast." if language == "ru" else "Spotify connected. Close this tab and return to KCromecast."
                status = 200
            except (ValueError, OSError):
                text = "Не удалось подключить Spotify. Вернитесь в KCromecast и повторите вход." if language == "ru" else "Spotify sign-in failed. Return to KCromecast and try again."
                status = 400
            body = ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                    "<title>KCromecast</title><style>body{font:18px system-ui;max-width:36em;margin:15vh auto;padding:2em;background:#202528;color:#e8eef0}</style>"
                    "<h1>KCromecast</h1><p>" + text + "</p>").encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.authorized():
            return
        if self.path != "/v1/state":
            self.reply(404, {"error": "Not found"})
            return
        self.reply(200, self.server.manager.snapshot())

    def do_POST(self):
        if not self.authorized():
            return
        if self.path not in ("/v1/command", "/v1/select", "/v1/reconnect", "/v1/spotify/authorize", "/v1/spotify/disconnect"):
            self.reply(404, {"error": "Not found"})
            return
        try:
            raw_length = self.headers.get("Content-Length", "0")
            if not raw_length.isdecimal() or len(raw_length) > 4:
                raise ValueError("Invalid request")
            length = int(raw_length)
            if not 0 < length <= 4096:
                raise ValueError("Invalid request")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Invalid request")
            manager = self.server.manager
            if self.path == "/v1/select":
                manager.select(data.get("device"))
            elif self.path == "/v1/reconnect":
                manager.reconnect()
            elif self.path == "/v1/spotify/authorize" and manager.spotify:
                url = manager.spotify.authorize(data.get("client_id"), data.get("language", "en"))
                self.reply(200, {"authorization_url": url})
                return
            elif self.path == "/v1/spotify/disconnect" and manager.spotify:
                manager.spotify.disconnect()
            else:
                if not isinstance(data.get("device"), str) or not isinstance(data.get("action"), str):
                    raise ValueError("Invalid request")
                manager.command(data["device"], data["action"], data.get("value"))
            self.reply(200, self.server.manager.snapshot())
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else "Invalid request"
            self.reply(400, {"error": message})
        except Exception:
            LOG.exception("Receiver command failed")
            self.reply(502, {"error": "The speakers did not respond. Try again."})


def main():
    parser = argparse.ArgumentParser(description="KCromecast background service")
    parser.add_argument("--port", type=int, default=17844)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--events-port", type=int, default=17845)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = json.loads(args.config.read_text())
    from .desktop import DesktopRuntime
    from .spotify import SpotifyConnect
    manager = Manager(state_dir=args.config.parent)
    manager.spotify = SpotifyConnect(args.config.parent, manager.changed, manager.artwork, args.port)
    server = LocalServer(("127.0.0.1", args.port), Handler)
    server.manager, server.token = manager, config["token"]
    def desktop_failed():
        threading.Thread(target=server.shutdown, daemon=True).start()
    desktop = DesktopRuntime(manager, config["token"], args.events_port, failure_callback=desktop_failed)
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        manager.start()
        desktop.start()
        LOG.info("KCromecast %s ready on loopback", __version__)
        server.serve_forever(poll_interval=.3)
        if desktop.failure:
            raise RuntimeError("Desktop event server stopped") from desktop.failure
    finally:
        desktop.stop()
        manager.stop()
        server.server_close()


if __name__ == "__main__":
    main()
