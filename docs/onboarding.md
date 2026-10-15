# Developer onboarding (T07)

Two ways to work, one environment definition. Code runs on serverless; laptops and Codespaces hold code,
not data.

## The environments

| Environment | Defined by | Used for |
|---|---|---|
| `envs/serverless-v4` | `databricks environments setup-local --serverless-version 4`: databricks-connect 17.3 and the package versions of serverless environment 4 as uv constraints | Fay's and Gus's notebooks and scripts over Databricks Connect; the same version the bundle pins for jobs (`var.serverless_environment_version`) |
| repo root | `pyproject.toml` and `uv.lock` | admin and CI tooling (scripts/), tests, generators; needs a newer `databricks-sdk` than serverless ships |

## Fay: local (VS Code)

```bash
uv sync --all-groups                                     # tooling
uv sync --project envs/serverless-v4 --all-groups       # Connect environment
uv run --project envs/serverless-v4 python scripts/connect_check.py --target dev
```

In VS Code with the Databricks extension, select `envs/serverless-v4/.venv` as the interpreter and open
`notebooks/fay_local.ipynb`. `spark` is a Databricks Connect session; `df.count()` runs on serverless.

## Gus: GitHub Codespace, as his service principal

1. Codespaces secrets for the repo: `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`
   (Gus's service principal, OAuth M2M). Set them in GitHub, never in files.
2. Create the Codespace. `.devcontainer/post_create.sh` installs uv and the CLI and both environments
   from the lockfiles, hash-checked, and prints the environment fingerprint.
3. `uv run --project envs/serverless-v4 python scripts/connect_check.py --target dev`

## Library sync between environments

1. A developer adds a dependency: `uv add <package>` (root) or `uv add --project envs/serverless-v4 <package>`.
2. Commit `pyproject.toml` and `uv.lock`; CI checks the lock is current and installs from it.
3. Others pull and run `uv sync` (or `scripts/install_from_lock.sh` where the lock's index is unreachable).
4. `scripts/env_fingerprint.sh envs/serverless-v4` must print the same hash everywhere.

The lockfiles were resolved through a package mirror. `uv.lock` records index URLs, and uv has no
mirror override (astral-sh/uv#6349, open), so CI and Codespaces install with `scripts/install_from_lock.sh`:
an export of the same versions and hashes, installed from public PyPI with `--require-hashes`.

## Rules

- No data on laptops: no `toPandas()` or `collect()` on large tables; `tests/test_no_data_in_repo.py`
  fails on tracked data files and local Spark or Delta artifacts.
- What works locally and what needs the workspace: `docs/parity.md` (tested, not assumed).
- Pipeline (SDP) code is validated or run by a bundle deploy to your own `dev` target, not over Connect.
