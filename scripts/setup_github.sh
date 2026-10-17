#!/usr/bin/env bash
# One-time GitHub setup for CI/CD (T09). Run it yourself: it creates a credential and changes repo settings.
#   1. A 90-day OAuth secret for the meridian-ci service principal, piped straight into the GitHub
#      environments ci, staging and prod as DATABRICKS_CLIENT_SECRET (held in a shell variable, sent on
#      stdin, never printed or written to disk), with DATABRICKS_CLIENT_ID and DATABRICKS_HOST beside it.
#   2. The prod environment requires a reviewer (you), for deploy.yml tags and rollback.yml.
#   3. Branch protection on main: passing `checks` and `integration` jobs (admins can still push).
# Needs: gh (authenticated, repo admin), the Databricks CLI profile in .env.local, uv.
#   scripts/setup_github.sh
# If the workspace refuses to create the secret here, generate one in the workspace UI (Settings, Identity and
# access, Service principals, meridian-ci, Secrets), copy it, and pass it on stdin instead:
#   pbpaste | scripts/setup_github.sh --secret-stdin
set -euo pipefail
secret_stdin=false
[ "${1:-}" = "--secret-stdin" ] && secret_stdin=true
cd "$(git rev-parse --show-toplevel)"
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }
repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
reviewer_id="$(gh api user -q .id)"

read -r sp_id sp_app_id host email < <(uv run --group dbx python - <<'PY'
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
sp = next(iter(w.service_principals.list(filter="displayName eq 'meridian-ci'")))
print(sp.id, sp.application_id, w.config.host, w.current_user.me().user_name)
PY
)

gh api -X PUT "repos/$repo/environments/ci" --silent
gh api -X PUT "repos/$repo/environments/staging" --silent
gh api -X PUT "repos/$repo/environments/prod" --silent --input - <<JSON
{"reviewers": [{"type": "User", "id": $reviewer_id}], "prevent_self_review": false}
JSON

if $secret_stdin; then
  secret=""
  IFS= read -r secret || true   # the clipboard has no trailing newline
  [ -n "$secret" ] || { echo "no secret on stdin" >&2; exit 1; }
else
  secret="$(uv run --group dbx python - "$sp_id" <<'PY'
import sys
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import PermissionDenied
try:
    s = WorkspaceClient().service_principal_secrets_proxy.create(service_principal_id=int(sys.argv[1]),
                                                                 lifetime=f"{90 * 24 * 3600}s")
except PermissionDenied as exc:
    sys.exit(f"The workspace refused to create a secret for meridian-ci: {str(exc).splitlines()[0][:120]}\n"
             "Generate one in the workspace UI (Settings, Identity and access, Service principals, meridian-ci,\n"
             "Secrets), copy it, then run: pbpaste | scripts/setup_github.sh --secret-stdin")
sys.stdout.write(s.secret)
PY
)"
fi
for env in ci staging prod; do
  gh secret set DATABRICKS_HOST --env "$env" --repo "$repo" --body "$host"
  gh secret set DATABRICKS_CLIENT_ID --env "$env" --repo "$repo" --body "$sp_app_id"
  gh variable set NOTIFICATION_EMAIL --env "$env" --repo "$repo" --body "$email"   # job failure emails
  printf '%s' "$secret" | gh secret set DATABRICKS_CLIENT_SECRET --env "$env" --repo "$repo"
done
unset secret

gh api -X PUT "repos/$repo/branches/main/protection" --silent --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["checks", "integration"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
gh variable set CI_READY --repo "$repo" --body true   # turns on the Databricks jobs in the workflows
echo "GitHub environments ci, staging, prod configured for $repo; main is protected (checks, integration)."
