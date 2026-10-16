"""Create or update the Genie space from config/genie_space.yaml (T22), and let the persona groups use it.

Builds the space's serialized definition (version 2: tables, one text instruction, example SQL, a failure-rate
measure, sample questions, benchmarks with golden SQL), with stable IDs so reruns update in place. The space is
found by title. Grants CAN RUN to the persona groups; Genie runs queries as the asking user, so Unity Catalog
grants and ABAC policies on the gold tables apply per user.

    uv run --group dbx python scripts/setup_genie.py --target prod
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml
from databricks.sdk import WorkspaceClient

from meridian.common.bundle import target_names
from meridian.common.workspace import warehouse_id

REPO = Path(__file__).resolve().parents[1]
GROUPS = ("meridian-support", "meridian-finance", "meridian-admin")


def hid(*parts: str) -> str:
    return hashlib.md5(":".join(parts).encode()).hexdigest()  # a stable 32-hex ID, not a security use


def serialized_space(spec: dict, gold: str) -> dict:
    def sub(text: str) -> str:
        return " ".join(text.format(gold=gold).split())

    return {
        "version": 2,
        "config": {"sample_questions": sorted(
            ({"id": hid("sample", q), "question": [q]} for q in spec["sample_questions"]), key=lambda x: x["id"])},
        "data_sources": {"tables": sorted(
            ({"identifier": f"{gold}.{t['name']}", "description": [" ".join(t["description"].split())]}
             for t in spec["tables"]), key=lambda x: x["identifier"])},
        "instructions": {
            "text_instructions": [{"id": hid("instructions"), "content": [" ".join(spec["instructions"].split())]}],
            "example_question_sqls": sorted(
                ({"id": hid("example", e["question"]), "question": [e["question"]], "sql": [sub(e["sql"])]}
                 for e in spec["example_sqls"]), key=lambda x: x["id"]),
            "sql_snippets": {"measures": sorted(
                ({"id": hid("measure", m["alias"]), "alias": m["alias"], "display_name": m["display_name"],
                  "sql": [m["sql"]]} for m in spec["measures"]), key=lambda x: x["id"])},
        },
        "benchmarks": {"questions": sorted(
            ({"id": hid("benchmark", b["question"]), "question": [b["question"]],
              "answer": [{"format": "SQL", "content": [sub(b["sql"])]}]} for b in spec["benchmarks"]),
            key=lambda x: x["id"])},
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="dev")
    args = p.parse_args()
    t = target_names(args.target)
    spec = yaml.safe_load((REPO / "config" / "genie_space.yaml").read_text())
    title = spec["title"] + ("" if args.target == "prod" else f" [{args.target}]")
    body = json.dumps(serialized_space(spec, f"{t.catalog}.{t.schemas['gold']}"))
    w = WorkspaceClient()
    existing = next((s for s in (w.genie.list_spaces().spaces or []) if s.title == title), None)
    if existing:
        w.genie.update_space(existing.space_id, serialized_space=body, title=title, description=spec["description"])
        space_id = existing.space_id
        print(f"updated Genie space {title}")
    else:
        space_id = w.genie.create_space(warehouse_id(w), body, title=title, description=spec["description"]).space_id
        print(f"created Genie space {title}")
    w.api_client.do("PATCH", f"/api/2.0/permissions/genie/{space_id}", body={
        "access_control_list": [{"group_name": g, "permission_level": "CAN_RUN"} for g in GROUPS]})
    print(f"CAN RUN for {', '.join(GROUPS)}; space id {space_id}")


if __name__ == "__main__":
    main()
