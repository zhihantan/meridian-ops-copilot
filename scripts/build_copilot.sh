#!/usr/bin/env bash
# Assemble the deployable copilot app (T17): the app code, the meridian package and the shared config it
# reads. The output sits outside the repo: deploy syncs the folder and honours the repo's .gitignore, which
# would skip a build folder inside it. No lockfile goes in: the Apps container resolves from public PyPI,
# and this repo's lockfiles name a package mirror it cannot reach.
#   scripts/build_copilot.sh     then: agentbricks deploy meridian-copilot --source "$(scripts/build_copilot.sh -p)"
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
out="${MERIDIAN_COPILOT_BUILD:-$HOME/.cache/meridian/copilot}"
[ "${1:-}" = -p ] && { echo "$out"; exit 0; }
rm -rf "$out" && mkdir -p "$out/config"
rsync -a --exclude .venv --exclude uv.lock --exclude .env --exclude __pycache__ --exclude .ruff_cache \
  apps/copilot/ "$out/"
rsync -a --exclude __pycache__ src/meridian "$out/"
cp config/scenario.yaml config/agent.yaml "$out/config/"
echo "built $out ($(find "$out" -name '*.py' | wc -l | tr -d ' ') Python files)"
