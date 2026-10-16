"""Parameterized SQL files: comment lines dropped, ${name} placeholders filled, split into statements.

Only ${name} is substituted, so regex anchors and other dollar signs in the SQL stay as they are. A
statement ends at a line ending in ';', except a CREATE PROCEDURE, which ends at its closing 'END;' at the
start of a line, so the statements inside its BEGIN ... END body stay together.
"""

from __future__ import annotations

import re
from pathlib import Path

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
PROCEDURE = re.compile(r"\s*CREATE\s+(OR\s+REPLACE\s+)?PROCEDURE\b", re.IGNORECASE)


def statements(path: str | Path, values: dict[str, str]) -> list[str]:
    body = "\n".join(line for line in Path(path).read_text().splitlines() if not line.lstrip().startswith("--"))
    missing = sorted({m.group(1) for m in PLACEHOLDER.finditer(body)} - set(values))
    if missing:
        raise KeyError(f"{path}: no value for {', '.join(missing)}")
    text = PLACEHOLDER.sub(lambda m: values[m.group(1)], body)
    out: list[str] = []
    buf: list[str] = []
    in_procedure = False
    for line in text.splitlines():
        if not buf and not line.strip():  # blank lines between statements
            continue
        if not buf and PROCEDURE.match(line):
            in_procedure = True
        buf.append(line)
        done = line.rstrip().upper() == "END;" if in_procedure else line.rstrip().endswith(";")  # END; at column 0
        if done:
            out.append("\n".join(buf).strip().rstrip(";"))
            buf, in_procedure = [], False
    if "\n".join(buf).strip():
        out.append("\n".join(buf).strip().rstrip(";"))
    return [s for s in out if s]
