"""Start a sync of this target's knowledge indexes after kb_sync writes chunks (T13).

The indexes use triggered sync, so new chunks reach search when this runs. Targets without indexes
(staging and ci) are skipped.

    sync_indexes.py --catalog C --bronze-schema S
"""

from __future__ import annotations

import sys
from pathlib import Path

# Serverless Python file tasks run without __file__, so the bundle passes --src-dir.
sys.path.insert(0, sys.argv[sys.argv.index("--src-dir") + 1] if "--src-dir" in sys.argv
                else str(Path(__file__).resolve().parents[2]))

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

from meridian.jobs.common import names, parser


def main() -> None:
    args = parser(__doc__.splitlines()[0]).parse_args()
    n = names(args)
    w = WorkspaceClient()
    for tier in ("general", "finance"):
        index = n.table("kb", f"idx_{tier}")
        try:
            w.vector_search_indexes.sync_index(index_name=index)
            print(f"sync started: {index}")
        except NotFound:
            print(f"no index {index} in this target; skipped")


if __name__ == "__main__":
    main()
