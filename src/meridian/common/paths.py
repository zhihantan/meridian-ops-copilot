"""Where shared config lives: the repo's config/ folder, or MERIDIAN_CONFIG_DIR in a packaged app."""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    return Path(os.environ.get("MERIDIAN_CONFIG_DIR") or Path(__file__).resolve().parents[3] / "config")
