"""Parameterized SQL files: comment lines dropped, ${...} placeholders filled, split into statements."""

from __future__ import annotations

from pathlib import Path
from string import Template


def statements(path: str | Path, values: dict[str, str]) -> list[str]:
    body = "\n".join(line for line in Path(path).read_text().splitlines() if not line.lstrip().startswith("--"))
    text = Template(body).substitute(values)
    return [s.strip().rstrip(";") for s in text.split(";\n") if s.strip().rstrip(";")]
