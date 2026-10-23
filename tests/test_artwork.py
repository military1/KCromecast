from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from kcromecast.artwork import ArtworkCache


class ArtworkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.changed = Mock()
        self.cache = ArtworkCache(self.directory, self.changed)
        self.addCleanup(self.cache.stop)

    @patch("kcromecast.artwork.urlopen")
    def test_large_artwork_is_decoded_once_to_a_small_jpeg(self, urlopen):
        source = BytesIO()
        Image.new("RGB", (2400, 1200), "red").save(source, "PNG")
        response = Mock(headers={"Content-Type": "image/png"})
        response.read.return_value = source.getvalue()
        urlopen.return_value.__enter__.return_value = response
        self.cache._load("https://example.com/large.png")
        path = next(self.directory.glob("*.jpg"))
        with Image.open(path) as image:
            self.assertEqual(image.size, (512, 256))
            self.assertEqual(image.format, "JPEG")
        self.assertLess(path.stat().st_size, len(source.getvalue()))
        self.cache._load("https://example.com/large.png")
        self.assertEqual(urlopen.call_count, 1)

    def test_cache_limit_removes_old_files_but_preserves_current_cover(self):
        protected = self.directory / "protected.jpg"
        protected.write_bytes(b"a" * 5)
        old = self.directory / "old.jpg"
        old.write_bytes(b"b" * 8)
        new = self.directory / "new.jpg"
        new.write_bytes(b"c" * 8)
        import os
        os.utime(old, (time.time() - 100, time.time() - 100))
        self.cache.protected = lambda: {protected.as_uri()}
        self.cache.max_bytes = 14
        self.cache.prune()
        self.assertTrue(protected.exists())
        self.assertTrue(new.exists())
        self.assertFalse(old.exists())

    @patch("kcromecast.artwork.urlopen")
    def test_failed_download_has_backoff_and_no_temporary_file(self, urlopen):
        urlopen.side_effect = OSError("offline")
        url = "https://example.com/broken.jpg"
        self.cache._load(url)
        self.cache.request(url)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(list(self.directory.iterdir()), [])
