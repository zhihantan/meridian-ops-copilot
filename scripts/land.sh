#!/usr/bin/env bash
# Land one generated batch into the watched raw volume, which fires the file-arrival trigger.
#   scripts/land.sh <target> <dataset>/<batch>      e.g. scripts/land.sh dev payments/incident
#   scripts/land.sh <target> kb                     the knowledge corpus: files by tier, Slack history
set -euo pipefail
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }  # local profile, no inline prefix needed
target="${1:?target}"
batch="${2:?dataset/batch, e.g. payments/incident}"
dataset="${batch%%/*}"
data="${DATA_DIR:-data/out}"

if [ "$batch" = kb ]; then
  # Files go to kb/files/<tier>/ (tier from the corpus manifest) with the manifest beside them; Slack
  # history pages go to kb/slack/history/<channel>/, users to kb/slack/users/.
  [ -f "$data/knowledge/manifest.csv" ] || { echo "no corpus at $data/knowledge (run make gen-corpus)" >&2; exit 1; }
  eval "$(uv run python scripts/volumes.py "$target")"
  root="dbfs:${RAW}/kb"
  uv run python - "$data" <<'PY' | while read -r src rel; do
import csv, sys
from pathlib import Path
data = Path(sys.argv[1])
for row in csv.DictReader((data / "knowledge" / "manifest.csv").open()):
    name = Path(row["path"]).name
    print(data / "knowledge" / name, f"files/{row['tier']}/{name}")
print(data / "knowledge" / "manifest.csv", "files/manifest.csv")
for page in sorted((data / "slack_export").glob("*.json")):
    if page.name != "users.json":
        print(page, f"slack/history/{page.stem}/{page.name}")
print(data / "slack_export" / "users.json", "slack/users/users.json")
PY
    databricks fs mkdirs "$root/$(dirname "$rel")" </dev/null
    databricks fs cp "$src" "$root/$rel" --overwrite </dev/null
  done
  exit 0
fi
src="${data}/${batch}"   # DATA_DIR: another generator output (the CI integration test)
[ -d "$src" ] || { echo "no generated batch at $src (run make gen-data)" >&2; exit 1; }

eval "$(uv run python scripts/volumes.py "$target")"
dest="dbfs:${RAW}/${dataset}"
echo "landing $(ls "$src" | wc -l | tr -d ' ') file(s) from $src into $dest"
databricks fs mkdirs "$dest"
for f in "$src"/*.json; do
  databricks fs cp "$f" "$dest/$(basename "$f")" --overwrite
done
