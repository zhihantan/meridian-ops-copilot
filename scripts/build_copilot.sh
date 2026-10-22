#!/usr/bin/env bash
# Assemble the deployable copilot app (T17): the app code, the meridian package, the shared config it
# reads, and the browser UI, built from apps/copilot/frontend (React and Vite) into runtime/static. The
# output sits outside the repo: deploy syncs the folder and honours the repo's .gitignore, which would skip
# a build folder inside it. No lockfile goes in: the Apps container resolves from public PyPI, and this
# repo's lockfiles name a package mirror it cannot reach. The UI's own source and node_modules stay out too.
# The About page's workspace links come from the bundle's summary of prod and staging (scripts/console_links.py),
# read with the CLI profile in DATABRICKS_CONFIG_PROFILE; without it the page shows the boxes without links.
#   scripts/build_copilot.sh     then: agentbricks deploy meridian-copilot --source "$(scripts/build_copilot.sh -p)"
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
out="${MERIDIAN_COPILOT_BUILD:-$HOME/.cache/meridian/copilot}"
[ "${1:-}" = -p ] && { echo "$out"; exit 0; }
(cd apps/copilot/frontend && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build >/dev/null)
rm -rf "$out" && mkdir -p "$out/config"
rsync -a --exclude .venv --exclude uv.lock --exclude .env --exclude __pycache__ --exclude .ruff_cache \
  --exclude frontend --exclude runtime/links.json apps/copilot/ "$out/"
rsync -a --exclude __pycache__ src/meridian "$out/"
cp config/scenario.yaml config/agent.yaml "$out/config/"
uv run --frozen python scripts/console_links.py --out "$out/runtime/links.json" \
  || echo "warning: no workspace links for the About page" >&2
echo "built $out ($(find "$out" -name '*.py' | wc -l | tr -d ' ') Python files, UI $(du -sh "$out/runtime/static" | cut -f1))"
