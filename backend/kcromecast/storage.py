"""Small private, atomic state files. Secrets never belong in widget config."""
import json
import os
from pathlib import Path
import tempfile


def read_json(path, default=None):
    try:
        value = Path(path).read_text(encoding="utf-8")
        data = json.loads(value)
        return data if isinstance(data, dict) else (default or {})
    except (OSError, ValueError):
        return default or {}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(stream.name, 0o600)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
