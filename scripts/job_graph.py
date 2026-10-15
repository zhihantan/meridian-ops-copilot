"""Cross-job graph of the bundle as Mermaid (T06, BUILD): docs/job_graph.md.

The Jobs UI shows one job's task DAG at a time. This draws every job and pipeline in a target, with
its triggers, task dependencies, run-job and pipeline tasks, and the tables that table-update triggers
watch. It shows what the bundle declares; a job that writes a watched table without declaring it (the
T06 backfill) is found from the table's history instead.

    uv run --group dbx python scripts/job_graph.py --target prod
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from meridian.common.localenv import load_local_env

load_local_env()

REPO = Path(__file__).resolve().parents[1]

REF = re.compile(r"\$\{resources\.(jobs|pipelines|schemas|volumes)\.([a-zA-Z0-9_]+)\.(id|name)\}")


def bundle_json(*args: str) -> dict:
    out = subprocess.run(["databricks", "bundle", *args, "-o", "json"], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def node_id(kind: str, key: str) -> str:
    return f"{kind}_{re.sub(r'[^a-zA-Z0-9_]', '_', key)}"


def resolve_names(text: str, config: dict) -> str:
    """Substitute schema and volume name references, which validate leaves unresolved."""
    def sub(m: re.Match) -> str:
        kind, key, attr = m.groups()
        if kind in ("schemas", "volumes") and attr == "name":
            return config["resources"][kind][key]["name"]
        return m.group(0)
    return REF.sub(sub, text)


def short_table(full: str) -> str:
    return ".".join(full.split(".")[-2:])


def trigger_label(job: dict, config: dict) -> tuple[str, list[str]] | None:
    """Trigger text and, for table-update triggers, the watched tables."""
    trig, sched = job.get("trigger") or {}, job.get("schedule")
    if "file_arrival" in trig:
        url = resolve_names(trig["file_arrival"]["url"], config)
        return f"file arrival<br/>{'/'.join(url.rstrip('/').split('/')[-2:])}/", []
    if "table_update" in trig:
        tables = [resolve_names(t, config) for t in trig["table_update"]["table_names"]]
        return f"table update<br/>{trig['table_update'].get('condition', 'ANY_UPDATED')}", tables
    if "periodic" in trig:
        p = trig["periodic"]
        return f"every {p['interval']} {p['unit'].lower()}", []
    if sched:
        return f"cron {sched['quartz_cron_expression']}<br/>{sched.get('timezone_id', 'UTC')}", []
    return None


def render(target: str) -> str:
    config = bundle_json("validate", "-t", target)
    jobs, pipelines = config["resources"].get("jobs", {}), config["resources"].get("pipelines", {})
    lines = ["flowchart LR"]
    edges: list[str] = []
    tables: dict[str, str] = {}

    for key, p in sorted(pipelines.items()):
        lines.append(f'  {node_id("pipeline", key)}[["pipeline: {p["name"]}"]]')

    generated = {k: j for k, j in jobs.items() if (j.get("tags") or {}).get("generated") == "true"}
    for key, job in sorted(jobs.items()):
        jid = node_id("job", key)
        trig = trigger_label(job, config)
        if trig:
            text, watched = trig
            lines.append(f'  {node_id("trigger", key)}(["{text}"])')
            edges.append(f"  {node_id('trigger', key)} --> {jid}")
            for t in watched:
                tables[t] = node_id("table", t)
                edges.append(f"  {tables[t]} --> {node_id('trigger', key)}")
        if key in generated:
            lines.append(f'  {jid}["{job["name"]}<br/><i>generated</i>"]')
            continue
        lines.append(f'  subgraph {jid}["{job["name"]}"]')
        lines.append("    direction TB")
        for task in job.get("tasks", []):
            tid = node_id("task", f"{key}__{task['task_key']}")
            run_if = task.get("run_if")
            label = task["task_key"] + (f"<br/><i>run_if {run_if}</i>" if run_if and run_if != "ALL_SUCCESS" else "")
            lines.append(f'    {tid}["{label}"]')
            for dep in task.get("depends_on", []):
                upstream = node_id("task", f"{key}__{dep['task_key']}")
                edges.append(f"  {upstream} --> {tid}")
            for field, kind in (("run_job_task", "jobs"), ("pipeline_task", "pipelines")):
                ref = task.get(field, {}).get("job_id" if kind == "jobs" else "pipeline_id", "")
                m = REF.search(str(ref))
                if m and m.group(1) == kind:
                    other = node_id("job" if kind == "jobs" else "pipeline", m.group(2))
                    edges.append(f"  {tid} -->|{'run job' if kind == 'jobs' else 'update'}| {other}")
        lines.append("  end")

    # A pipeline publishes the watched tables whose schema it writes (from its configuration).
    for key, p in pipelines.items():
        published = {resolve_names(str(v), config) for v in (p.get("configuration") or {}).values()}
        for t, tid in tables.items():
            if t.split(".")[1] in published:
                edges.append(f"  {node_id('pipeline', key)} -->|publishes| {tid}")
    for t, tid in sorted(tables.items()):
        lines.append(f'  {tid}[("{short_table(t)}")]')

    return "\n".join(lines + sorted(set(edges)))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", default="prod")
    p.add_argument("--out", default=str(REPO / "docs" / "job_graph.md"))
    args = p.parse_args()
    graph = render(args.target)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    doc = (f"# Job graph (target `{args.target}`)\n\n"
           "BUILD: generated by `scripts/job_graph.py` from the bundle configuration "
           f"on {stamp}; do not edit by hand.\n"
           "Edges are declared in the bundle: triggers, task dependencies, run-job and pipeline tasks, and the "
           "tables that table-update triggers watch. Writes that no bundle declares show up in table history.\n\n"
           f"```mermaid\n{graph}\n```\n")
    Path(args.out).write_text(doc)
    print(f"wrote {Path(args.out).relative_to(REPO)} ({graph.count(chr(10)) + 1} lines)")


if __name__ == "__main__":
    main()
