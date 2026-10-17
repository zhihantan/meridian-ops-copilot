#!/usr/bin/env bash
# One-time GitHub setup for CI/CD (T09). It creates a credential and changes repo settings.
#   1. A 90-day token on behalf of the meridian-ci service principal, piped straight into the GitHub
#      environments ci, staging and prod as DATABRICKS_TOKEN (held in a shell variable, sent on stdin, never
#      printed or written to disk), with DATABRICKS_HOST and the principal's application ID beside it.
#      meridian-ci first gets permission to use tokens.
#      OAuth M2M would be preferred, but creating an OAuth secret for meridian-ci needs its Service Principal
#      Manager role, which this workspace's admins do not hold (observed 2026-10-17), and GitHub OIDC
#      federation needs an account admin.
#   2. The prod environment requires a reviewer (you), for deploy.yml tags and rollback.yml.
#   3. Branch protection on main: passing `checks` and `integration` jobs (admins can still push).
# Needs: gh (authenticated, repo admin), the Databricks CLI profile in .env.local (a workspace admin), uv.
#   scripts/setup_github.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }
repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
reviewer_id="$(gh api user -q .id)"

read -r sp_app_id host email < <(uv run --group dbx python - <<'PY'
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
sp = next(iter(w.service_principals.list(filter="displayName eq 'meridian-ci'")))
print(sp.application_id, w.config.host, w.current_user.me().user_name)
PY
)

gh api -X PUT "repos/$repo/environments/ci" --silent
gh api -X PUT "repos/$repo/environments/staging" --silent
gh api -X PUT "repos/$repo/environments/prod" --silent --input - <<JSON
{"reviewers": [{"type": "User", "id": $reviewer_id}], "prevent_self_review": false}
JSON

token="$(uv run --group dbx python - "$sp_app_id" <<'PY'
import sys
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.settings import TokenAccessControlRequest, TokenPermissionLevel
w, app_id = WorkspaceClient(), sys.argv[1]
w.token_management.update_permissions(access_control_list=[  # adds to the list; admins keep CAN_MANAGE
    TokenAccessControlRequest(service_principal_name=app_id, permission_level=TokenPermissionLevel.CAN_USE)])
t = w.token_management.create_obo_token(application_id=app_id, lifetime_seconds=90 * 24 * 3600,
                                        comment="meridian GitHub Actions (T09), set by scripts/setup_github.sh")
sys.stdout.write(t.token_value)
PY
)"
for env in ci staging prod; do
  gh secret set DATABRICKS_HOST --env "$env" --repo "$repo" --body "$host"
  gh secret set DATABRICKS_CLIENT_ID --env "$env" --repo "$repo" --body "$sp_app_id"   # the bundle's run-as
  gh variable set NOTIFICATION_EMAIL --env "$env" --repo "$repo" --body "$email"   # job failure emails
  printf '%s' "$token" | gh secret set DATABRICKS_TOKEN --env "$env" --repo "$repo"
done
unset token

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
