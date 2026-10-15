#!/usr/bin/env bash
# Land one generated batch into the watched raw volume, which fires the file-arrival trigger.
#   scripts/land.sh <target> <dataset>/<batch>      e.g. scripts/land.sh dev payments/incident
set -euo pipefail
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }  # local profile, no inline prefix needed
target="${1:?target}"
batch="${2:?dataset/batch, e.g. payments/incident}"
dataset="${batch%%/*}"
src="data/out/${batch}"
[ -d "$src" ] || { echo "no generated batch at $src (run make gen-data)" >&2; exit 1; }

eval "$(uv run python scripts/volumes.py "$target")"
dest="dbfs:${RAW}/${dataset}"
echo "landing $(ls "$src" | wc -l | tr -d ' ') file(s) from $src into $dest"
databricks fs mkdirs "$dest"
for f in "$src"/*.json; do
  databricks fs cp "$f" "$dest/$(basename "$f")" --overwrite
done
