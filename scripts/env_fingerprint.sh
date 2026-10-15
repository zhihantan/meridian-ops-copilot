#!/usr/bin/env bash
# Fingerprint of an installed environment (T07): sha256 of the sorted package list, editable installs
# excluded (their paths differ per machine). Equal fingerprints mean identical package sets.
#   scripts/env_fingerprint.sh [project-dir]
set -euo pipefail
project="${1:-.}"
uv pip freeze --python "$project/.venv/bin/python" --exclude-editable | LC_ALL=C sort | shasum -a 256 | cut -d' ' -f1
