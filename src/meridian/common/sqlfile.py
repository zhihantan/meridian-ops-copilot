"""Parameterized SQL files: comment lines dropped, ${name} placeholders filled, split into statements.

Only ${name} is substituted, so regex anchors and other dollar signs in the SQL stay as they are.
"""

from __future__ import annotations

import re
from pathlib import Path

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def statements(path: str | Path, values: dict[str, str]) -> list[str]:
    body = "\n".join(line for line in Path(path).read_text().splitlines() if not line.lstrip().startswith("--"))
    missing = sorted({m.group(1) for m in PLACEHOLDER.finditer(body)} - set(values))
    if missing:
        raise KeyError(f"{path}: no value for {', '.join(missing)}")
    text = PLACEHOLDER.sub(lambda m: values[m.group(1)], body)
    return [s.strip().rstrip(";") for s in text.split(";\n") if s.strip().rstrip(";")]
