#!/usr/bin/env bash
# Install a project's locked environment on a machine that cannot reach the index in uv.lock (T07, T09).
# The lockfiles here were resolved through a package mirror that CI and Codespaces cannot reach. The
# export keeps every pinned version and hash, and --require-hashes fails the install unless each file is
# byte-identical to the locked one. Then the repo itself is installed editable, without dependencies.
#   scripts/install_from_lock.sh [project-dir]     (default: repo root; or envs/serverless-v4)
set -euo pipefail
root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
project="$(cd "${1:-$root}" && pwd)"
requirements="$(mktemp)"
trap 'rm -f "$requirements"' EXIT
cd "$project"
uv export --frozen --all-groups --no-emit-project --no-emit-package meridian --format requirements-txt \
  --output-file "$requirements" >/dev/null
uv venv --python 3.12 --allow-existing --quiet
uv pip sync --require-hashes --quiet "$requirements"
uv pip install --no-deps --quiet -e "$root"
echo "installed $(uv pip list --quiet 2>/dev/null | tail -n +3 | wc -l | tr -d ' ') packages into $project/.venv"
