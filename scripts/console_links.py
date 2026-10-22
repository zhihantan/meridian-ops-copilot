"""Workspace links for the console's About page (T17, BUILD), written into the app build by build_copilot.sh.

The bundle knows what it deployed: `databricks bundle summary` lists every job, pipeline and dashboard of a target
with its ID and workspace URL. This keeps the path and query of each URL, never the host, so the file names no
workspace; the app adds its own host when it serves the page. It also keeps the bundle's search and embedding
endpoint names, the prod deployment folder and the repository's GitHub URL. Whatever cannot be read is left out,
and the page shows that box without a link.

    uv run --frozen python scripts/console_links.py --out ~/.cache/meridian/copilot/runtime/links.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from meridian.common.localenv import load_local_env

load_local_env()

TARGETS = ("prod", "staging")  # dev is one copy per developer, so the console links to none of them
KINDS = {"jobs": "job", "pipelines": "pipeline", "dashboards": "dashboard"}
VARIABLES = ("search_endpoint", "embedding_endpoint")


def cli(*args: str) -> dict:
    out = subprocess.run(["databricks", *args, "-o", "json"], capture_output=True, text=True, check=True, timeout=120)
    return json.loads(out.stdout)


def path_of(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def github_url() -> str | None:
    try:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True,
                                check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    m = re.fullmatch(r"(?:https://|git@)github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?", remote)
    return f"https://github.com/{m[1]}/{m[2]}" if m else None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    links: dict = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "paths": {}, "variables": {},
                   "github": github_url()}
    for target in TARGETS:
        try:
            summary = cli("bundle", "summary", "-t", target)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            print(f"warning: no {target} links ({type(exc).__name__}); the About page shows those boxes without one",
                  file=sys.stderr)
            continue
        prefix = "" if target == "prod" else f"{target}/"
        for kind, ref in KINDS.items():
            for key, resource in (summary.get("resources", {}).get(kind) or {}).items():
                if resource.get("url"):
                    links["paths"][f"{ref}:{prefix}{key}"] = path_of(resource["url"])
        if target != "prod":
            continue
        variables = summary.get("variables", {})
        links["variables"] = {k: variables[k]["value"] for k in VARIABLES if "value" in variables.get(k, {})}
        try:  # the deployed files, owned by the release principal
            folder = cli("workspace", "get-status", summary["workspace"]["root_path"])
            links["paths"]["folder:prod"] = f"/browse/folders/{folder['object_id']}"
        except (KeyError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
            print("warning: no link to the prod deployment folder", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(links, indent=2) + "\n")
    print(f"links: {len(links['paths'])} workspace paths for the About page", file=sys.stderr)


if __name__ == "__main__":
    main()
