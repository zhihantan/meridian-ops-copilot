"""Ask the deployed copilot live, as a persona (run of show, scenes 5 and 6).

Ava, Ben and Gus are service principals, which cannot sign in to the workspace UI, so the presenter asks as them
from a terminal with their own tokens; every tool then runs as that persona. Eli is the presenter's own profile.
Follow-up questions continue the persona's conversation; --new starts over. The conversation is kept in /tmp only.

    uv run --group dbx --group agent python scripts/ask.py --as ben "acq_7 is degraded. Run RB-014 for acq_7 over the last 24 hours"
    uv run --group dbx --group agent python scripts/ask.py --as ben "Eli approved it. Continue the run."
    uv run --group dbx --group agent python scripts/ask.py --as ava --new "acq_7 is degraded. Run RB-014 for acq_7 over the last 24 hours"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from databricks.sdk import WorkspaceClient

from meridian.agent.client import ask
from meridian.common.workspace import bearer_token

APP = "agent-bricks-meridian-copilot"
PROFILES = {"ava": "meridian-ava", "ben": "meridian-ben", "gus": "meridian-gus", "eli": None}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--as", dest="persona", choices=PROFILES, required=True)
    p.add_argument("--new", action="store_true", help="start a new conversation for this persona")
    p.add_argument("question")
    args = p.parse_args()
    state = Path(f"/tmp/meridian_ask_{args.persona}.json")
    history = [] if args.new or not state.exists() else json.loads(state.read_text())

    profile = PROFILES[args.persona]
    caller = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    url = WorkspaceClient().apps.get(APP).url
    a = ask(url, bearer_token(caller), args.question, background=True, history=history)

    print(a["answer"])
    print(f"\n[{args.persona}, {a['seconds']} s; tools: {', '.join(a['tools']) or 'none'}; "
          f"knowledge cited: {', '.join(a['kb_citations']) or 'none'}]")
    state.write_text(json.dumps(history + [{"role": "user", "content": args.question},
                                           {"role": "assistant", "content": a["answer"]}]))


if __name__ == "__main__":
    main()
