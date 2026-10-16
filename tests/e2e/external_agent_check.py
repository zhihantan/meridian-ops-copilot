"""External agent check (T24): run examples/external_agent/agent.py as Ava and Ben, outside the project.

The agent runs from a temporary folder in an isolated environment with only the anthropic package (uv run
--isolated --no-project --with anthropic), so no Databricks library is importable. Each persona's token is
minted here with the Databricks SDK and passed in DATABRICKS_TOKEN; the agent itself only makes HTTPS calls.
Ava must be refused on the finance fee and still get the cited refund threshold; Ben gets both.
Writes docs/evidence/T24/external_agent.json.

    uv run --group dbx python tests/e2e/external_agent_check.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.common.workspace import bearer_token

REPO = Path(__file__).resolve().parents[2]
AGENT = REPO / "examples" / "external_agent" / "agent.py"
QUESTION = "What does acq_2 charge for a bank transfer payment, and above what amount does a refund batch need approval?"
CITATION = re.compile(r"\[([A-Z][A-Z0-9-]+) p\.\d+\]")


def run_as(profile: str, host: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env |= {"DATABRICKS_HOST": host, "DATABRICKS_TOKEN": bearer_token(WorkspaceClient(profile=profile))}
    with tempfile.TemporaryDirectory() as outside:
        out = subprocess.run(["uv", "run", "--isolated", "--no-project", "--quiet", "--with", "anthropic",
                              "python", "-I", str(AGENT), QUESTION], cwd=outside, env=env, capture_output=True,
                             text=True, timeout=600, check=False)
    answer = out.stdout.strip() or out.stderr.strip()[-500:]
    return {"answer": answer, "cited": sorted(set(CITATION.findall(answer))), "exit": out.returncode}


def main() -> None:
    host = WorkspaceClient().config.host.rstrip("/")
    ava, ben = run_as("meridian-ava", host), run_as("meridian-ben", host)
    checks = {
        "the agent ran outside the project with only the anthropic package": ava["exit"] == 0 and ben["exit"] == 0,
        "Ava: the finance fee is refused, not answered": "0.75" not in ava["answer"]
            and bool(re.search(r"(?i)permission|refused|denied|not have access", ava["answer"])),
        "Ava: the refund threshold is answered with a citation": "500" in ava["answer"]
            and bool({"DOC-RB-021", "DOC-REF-003"} & set(ava["cited"])),
        "Ben: the fee is answered from the finance document": "0.75" in ben["answer"] and "DOC-FEE-001" in ben["cited"],
    }
    result = {"task": "T24 external agent", "at": datetime.now(UTC).isoformat(), "question": QUESTION,
              "runtime": "uv run --isolated --no-project --with anthropic, from a temporary folder",
              "ava": ava, "ben": ben, "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}
    out = REPO / "docs" / "evidence" / "T24" / "external_agent.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"], json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
