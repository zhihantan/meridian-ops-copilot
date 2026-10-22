"""The console's About page (BUILD): the architecture, with each part linked to where it lives in the workspace.

GET /api/about gives the page the workspace host and the paths it links to, so neither the page nor any file in
the repo names a workspace. Bundle resources (jobs, pipelines, the dashboard, the prod deployment folder) come
from runtime/links.json, which scripts/console_links.py writes into the build from `databricks bundle summary`.
The page derives Unity Catalog objects from their names. The rest is known here: the Genie space by its title (it
is not a bundle resource), and the app, its trace experiment and the model endpoints from the app's settings.
It runs as the visitor, like every other request, so a Genie space they cannot open gets no link.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Request

from meridian.agent.answer import CONFIG
from runtime import genie
from runtime.visitor import as_visitor

router = APIRouter(prefix="/api/about")
LINKS_FILE = Path(__file__).parent / "links.json"
LINKS = json.loads(LINKS_FILE.read_text()) if LINKS_FILE.exists() else {}


@router.get("")
async def about(request: Request) -> dict:
    catalog = os.environ.get("MERIDIAN_KB_SCHEMA", "meridian.kb").split(".")[0]
    variables = LINKS.get("variables", {})
    names = {"answer_model": CONFIG["answer_model"],
             "embedding_model": variables.get("embedding_endpoint", "databricks-gte-large-en"),
             "search_endpoint": variables.get("search_endpoint", "meridian-search"),
             "genie_space": genie.TITLE}
    paths = {**LINKS.get("paths", {}),
             "endpoint:answer": f"/ml/endpoints/{names['answer_model']}",
             "endpoint:embedding": f"/ml/endpoints/{names['embedding_model']}",
             "search": f"/compute/vector-search/{names['search_endpoint']}"}
    if os.environ.get("DATABRICKS_APP_NAME"):
        paths["app"] = f"/apps/{os.environ['DATABRICKS_APP_NAME']}"
    if os.environ.get("MLFLOW_EXPERIMENT_ID"):
        paths["experiment"] = f"/ml/experiments/{os.environ['MLFLOW_EXPERIMENT_ID']}"

    def work(w: WorkspaceClient) -> dict:
        try:
            space = genie.space_id(w)
        except Exception:  # noqa: BLE001  not shared with this visitor, or Genie is unavailable: no link
            space = None
        if space:
            paths["genie"] = f"/genie/rooms/{space}"
        return {"host": (w.config.host or "").rstrip("/"), "catalog": catalog, "paths": paths, "names": names,
                "github": LINKS.get("github"), "links_generated_at": LINKS.get("generated_at")}

    return await as_visitor(request, work)
