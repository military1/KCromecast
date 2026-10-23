"""Persistent Cast connections and an authenticated, loopback-only UI API.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import dataclass, field
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
from pathlib import Path
import secrets
import signal
import threading
import time
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pychromecast
from pychromecast.discovery import AbstractCastListener, CastBrowser
from zeroconf import Zeroconf

from . import __version__

LOG = logging.getLogger("kcromecast")
CONFIG = Path.home() / ".config/kcromecast/service.json"
CACHE = Path.home() / ".cache/kcromecast/artwork"
ACTIVE = {"PLAYING", "PAUSED", "BUFFERING"}


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


def media_snapshot(status):
    """Normalize receiver data; never expose media URLs, tokens or session IDs."""
    metadata = status.media_metadata or {}
    images = sorted(metadata.get("images", []), key=lambda i: finite(i.get("width")), reverse=True)
    artwork = next((i["url"] for i in images if urlsplit(i.get("url", "")).scheme == "https"), "")
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
    command_lock: threading.Lock = field(default_factory=threading.Lock)


class StatusListener:
    def __init__(self, manager, device_id):
        self.manager, self.device_id = manager, device_id

    def new_media_status(self, status):
        self.manager.update_media(self.device_id, status)

    def load_media_failed(self, queue_item_id, error_code):
        LOG.info("Receiver reported a media error: %s", error_code)

    def new_cast_status(self, status):
        with self.manager.lock:
            device = self.manager.devices.get(self.device_id)
            if device:
                device.receiver = {
                    "volume": round(max(0, min(1, finite(status.volume_level))) * 100),
                    "muted": bool(status.volume_muted),
                    "app": str(status.display_name or ""),
                    "service": service_name(status.display_name),
                }

    def new_connection_status(self, status):
        with self.manager.lock:
            device = self.manager.devices.get(self.device_id)
            if device:
                device.connected = status.status == "CONNECTED"


class DiscoveryListener(AbstractCastListener):
    def __init__(self, manager):
        self.manager = manager

    def add_cast(self, uuid, service):
        self.manager.discover(uuid)

    def update_cast(self, uuid, service):
        self.manager.discover(uuid)

    def remove_cast(self, uuid, service, cast_info):
        # A group can move to another leader/port. Keep its identity and let
        # PyChromecast reconnect using the live mDNS services, rather than
        # deleting it when just one announcement disappears.
        pass


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.devices: dict[str, Device] = {}
        self.connecting = set()
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cast")
        self.zc = Zeroconf()
        self.browser = CastBrowser(DiscoveryListener(self), self.zc)
        self.stopping = threading.Event()
        self.sleep_device = ""
        self.sleep_deadline = 0.0
        self.sleep_minutes = 0
        self.error = ""
        CACHE.mkdir(parents=True, exist_ok=True)
        self.pending_artwork = set()

    def start(self):
        self.browser.start_discovery()
        threading.Thread(target=self.timer_loop, daemon=True, name="sleep-timer").start()

    def discover(self, uuid):
        key = str(uuid)
        info = self.browser.devices.get(uuid)
        if not info:
            return
        with self.lock:
            if key in self.devices:
                self.devices[key].name = info.friendly_name or "Chromecast"
                return
            if key in self.connecting or self.stopping.is_set():
                return
            self.connecting.add(key)
        self.pool.submit(self.connect, info)

    def connect(self, info):
        key = str(info.uuid)
        cast = None
        try:
            cast = pychromecast.get_chromecast_from_cast_info(info, self.zc, timeout=8, retry_wait=3)
            device = Device(key, info.friendly_name or "Chromecast", info.model_name or "",
                            cast.cast_type == "group", cast)
            with self.lock:
                self.devices[key] = device
            listener = StatusListener(self, key)
            cast.register_status_listener(listener)
            cast.register_connection_listener(listener)
            cast.media_controller.register_status_listener(listener)
            cast.start()
        except Exception:
            LOG.exception("Could not connect to a Cast receiver")
            with self.lock:
                self.devices.pop(key, None)
            if cast:
                cast.disconnect()
        finally:
            with self.lock:
                self.connecting.discard(key)

    def update_media(self, key, status):
        snapshot = media_snapshot(status)
        url = snapshot.pop("artwork_remote")
        with self.lock:
            device = self.devices.get(key)
            if not device:
                return
            device.media, device.updated = snapshot, time.monotonic()
            if device.artwork_remote != url:
                device.artwork_remote, device.artwork = url, ""
            if url and not device.artwork and (key, url) not in self.pending_artwork:
                self.pending_artwork.add((key, url))
                self.pool.submit(self.cache_artwork, key, url)

    def cache_artwork(self, key, url):
        path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".jpg")
        try:
            if not path.exists():
                with urlopen(Request(url, headers={"User-Agent": "KCromecast/1.0"}), timeout=12) as response:
                    if not response.headers.get("Content-Type", "").startswith("image/"):
                        return
                    data = response.read(4 * 1024 * 1024 + 1)
                    if len(data) > 4 * 1024 * 1024:
                        return
                    with tempfile.NamedTemporaryFile(dir=CACHE, suffix=".tmp", delete=False) as handle:
                        handle.write(data)
                        temporary = Path(handle.name)
                    temporary.replace(path)
            with self.lock:
                device = self.devices.get(key)
                if device and device.artwork_remote == url:
                    device.artwork = path.as_uri()
            # Bound disk use while keeping the current session's artwork.
            files = sorted(CACHE.glob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True)
            for old in files[128:]:
                old.unlink(missing_ok=True)
        except Exception:
            LOG.debug("Artwork unavailable", exc_info=True)
        finally:
            with self.lock:
                self.pending_artwork.discard((key, url))

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            devices = []
            for device in self.devices.values():
                media = copy.deepcopy(device.media)
                if media.get("state") == "PLAYING":
                    media["position"] = media.get("position", 0) + now - device.updated
                    if media.get("duration"):
                        media["position"] = min(media["position"], media["duration"])
                devices.append({"id": device.id, "name": device.name, "model": device.model,
                                "group": device.group, "connected": device.connected,
                                **media, **device.receiver, "artwork": device.artwork})
            devices.sort(key=lambda d: (not d["group"], d["name"].casefold()))
            return {"version": __version__, "sampled_at": now, "devices": devices,
                    "sleep": {"device": self.sleep_device, "remaining": max(0, math.ceil(self.sleep_deadline - now)),
                              "minutes": self.sleep_minutes}, "error": self.error}

    def command(self, key, action, value=None):
        with self.lock:
            device = self.devices.get(key)
            if not device or not device.connected:
                raise ValueError("The speakers are unavailable. Check your network connection.")
        if action == "sleep":
            minutes = finite(value, -1)
            if minutes not in (0, 15, 30, 45, 60, 90):
                raise ValueError("Invalid sleep timer")
            with self.lock:
                self.sleep_device = key if minutes else ""
                self.sleep_deadline = time.monotonic() + minutes * 60 if minutes else 0
                self.sleep_minutes = int(minutes)
                self.error = ""
            return
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

    def timer_loop(self):
        while not self.stopping.wait(.5):
            with self.lock:
                if not self.sleep_deadline or time.monotonic() < self.sleep_deadline:
                    continue
                key = self.sleep_device
                self.sleep_device, self.sleep_deadline, self.sleep_minutes = "", 0, 0
            try:
                with self.lock:
                    device = self.devices.get(key)
                    playing = device and device.media.get("state") in ("PLAYING", "BUFFERING")
                if playing:
                    self.command(key, "pause")
            except Exception:
                with self.lock:
                    self.error = "The sleep timer ended, but the speakers did not respond."
                LOG.exception("Sleep timer could not pause the receiver")

    def stop(self):
        self.stopping.set()
        self.browser.stop_discovery()
        with self.lock:
            casts = [d.cast for d in self.devices.values()]
        for cast in casts:
            try:
                cast.disconnect(timeout=2)
            except Exception:
                pass
        self.zc.close()
        self.pool.shutdown(wait=False, cancel_futures=True)


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
        valid = (self.headers.get("Host") == expected_host and
                 secrets.compare_digest(auth, "Bearer " + self.server.token))
        if not valid:
            self.reply(403, {"error": "Unauthorized"})
        return valid

    def do_GET(self):
        if not self.authorized():
            return
        if self.path != "/v1/state":
            self.reply(404, {"error": "Not found"})
            return
        self.reply(200, self.server.manager.snapshot())

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/v1/command":
            self.reply(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("Invalid request")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Invalid request")
            self.server.manager.command(data.get("device"), data.get("action"), data.get("value"))
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
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = json.loads(args.config.read_text())
    manager = Manager()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.manager, server.token = manager, config["token"]
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    manager.start()
    LOG.info("KCromecast %s ready on loopback", __version__)
    try:
        server.serve_forever(poll_interval=.3)
    finally:
        manager.stop()
        server.server_close()


if __name__ == "__main__":
    main()
