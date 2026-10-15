#!/usr/bin/env bash
# Codespace setup (T07): uv, the Databricks CLI, and both environments from the committed lockfiles,
# hash-checked. Auth comes from the Codespaces secrets in devcontainer.json (OAuth M2M), never files.
set -euo pipefail
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sudo sh
export PATH="$HOME/.local/bin:$PATH"
bash scripts/install_from_lock.sh
bash scripts/install_from_lock.sh envs/serverless-v4
echo "serverless-v4 fingerprint: $(bash scripts/env_fingerprint.sh envs/serverless-v4)"
