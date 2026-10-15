"""Print resolved Volume paths for a bundle target as shell assignments, e.g. RAW=/Volumes/...

    eval "$(uv run python scripts/volumes.py dev)"

`bundle validate -o json` leaves cross-resource references such as ${resources.schemas.landing.name}
unresolved, so they are substituted here from the resolved schema names in the same output.
"""

import json
import re
import subprocess
import sys

target = sys.argv[1] if len(sys.argv) > 1 else "dev"
result = subprocess.run(
    ["databricks", "bundle", "validate", "-t", target, "-o", "json"], capture_output=True, text=True, check=True
)
config = json.loads(result.stdout)
schemas = {key: s["name"] for key, s in config["resources"]["schemas"].items()}


def resolve(value: str) -> str:
    return re.sub(r"\$\{resources\.schemas\.(\w+)\.name\}", lambda m: schemas[m.group(1)], value)


for key, volume in config["resources"]["volumes"].items():
    print(f"{key.upper()}=/Volumes/{volume['catalog_name']}/{resolve(volume['schema_name'])}/{volume['name']}")
print(f"CATALOG={config['variables']['catalog']['value']}")
for key, name in schemas.items():
    print(f"SCHEMA_{key.upper()}={name}")
