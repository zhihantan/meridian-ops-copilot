"""Load KEY=VALUE pairs from the repo's gitignored .env.local into os.environ (local tooling only).

Lets commands run without an inline `DATABRICKS_CONFIG_PROFILE=...` prefix. Values already set in
the environment win. The file is never synced to the workspace or committed.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[3] / ".env.local"


def load_local_env(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
