"""Deduplicated, size-bounded thumbnails with a separate, small I/O pool."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import logging
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

LOG = logging.getLogger("kcromecast.artwork")
Image.MAX_IMAGE_PIXELS = 16_000_000


class ArtworkCache:
    def __init__(self, directory, changed, protected=lambda: set(), max_bytes=64 * 1024 * 1024):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.changed, self.protected, self.max_bytes = changed, protected, max_bytes
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="artwork")
        self.lock = threading.Lock()
        self.pending, self.failed = set(), {}
        self.closed = False

    def request(self, url):
        if not url.startswith("https://"):
            return
        with self.lock:
            if self.closed or len(self.pending) >= 32 or url in self.pending or self.failed.get(url, 0) > time.monotonic():
                return
            self.pending.add(url)
            self.pool.submit(self._load, url)

    def _load(self, url):
        path = self.directory / ("v2-" + hashlib.sha256(url.encode()).hexdigest() + ".jpg")
        temporary = path.with_suffix(".tmp")
        try:
            if not path.exists():
                request = Request(url, headers={"User-Agent": "KCromecast/1.1"})
                with urlopen(request, timeout=8) as response:
                    if not response.headers.get("Content-Type", "").startswith("image/"):
                        raise ValueError("Not an image")
                    data = response.read(4 * 1024 * 1024 + 1)
                    if len(data) > 4 * 1024 * 1024:
                        raise ValueError("Artwork too large")
                with Image.open(BytesIO(data)) as original:
                    image = ImageOps.exif_transpose(original)
                    image.thumbnail((512, 512), Image.Resampling.LANCZOS)
                    image.convert("RGB").save(temporary, "JPEG", quality=86, optimize=True)
                temporary.replace(path)
            path.touch()
            self.changed(url, path.as_uri())
            self.prune()
        except Exception:
            with self.lock:
                # Bound failure history as well as the on-disk cache.
                self.failed = {key: until for key, until in self.failed.items() if until > time.monotonic()}
                if len(self.failed) >= 128:
                    self.failed.pop(next(iter(self.failed)))
                self.failed[url] = time.monotonic() + 60
            LOG.debug("Artwork unavailable", exc_info=True)
        finally:
            temporary.unlink(missing_ok=True)
            with self.lock:
                self.pending.discard(url)

    def prune(self):
        protected = self.protected()
        with self.lock:
            files = []
            for path in self.directory.glob("*.jpg"):
                try:
                    stat = path.stat()
                    files.append((stat.st_mtime, stat.st_size, path))
                except FileNotFoundError:
                    pass
            files.sort(reverse=True)
            total, count = 0, 0
            for _, size, path in files:
                if path.as_uri() in protected or (count < 128 and total + size <= self.max_bytes):
                    total += size
                    count += 1
                else:
                    path.unlink(missing_ok=True)

    def stop(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
