"""User data locations shared by the service and installer."""
import os
from pathlib import Path


def xdg_path(variable, fallback):
    value = os.environ.get(variable, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


CONFIG_DIR = xdg_path("XDG_CONFIG_HOME", ".config") / "kcromecast"
DATA_DIR = xdg_path("XDG_DATA_HOME", ".local/share") / "kcromecast"
CACHE_DIR = xdg_path("XDG_CACHE_HOME", ".cache") / "kcromecast"
