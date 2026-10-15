"""Print resolved Volume paths for a bundle target as shell assignments, e.g. RAW=/Volumes/...

    eval "$(uv run python scripts/volumes.py dev)"
"""

import json
import subprocess
import sys

target = sys.argv[1] if len(sys.argv) > 1 else "dev"
result = subprocess.run(
    ["databricks", "bundle", "validate", "-t", target, "-o", "json"], capture_output=True, text=True, check=True
)
config = json.loads(result.stdout)
for key, volume in config["resources"]["volumes"].items():
    print(f"{key.upper()}=/Volumes/{volume['catalog_name']}/{volume['schema_name']}/{volume['name']}")
print(f"CATALOG={config['variables']['catalog']['value']}")
