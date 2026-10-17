# Onboarding: develop in the workspace

Everything is developed and deployed inside the Databricks workspace. GitHub holds the code: the bundle
(`databricks.yml`, `resources/`), the pipeline and job code, contracts, SQL and dashboards. Nothing is installed on
a laptop, and no data leaves the workspace. Bundles in the workspace need workspace files, Git folders and
serverless compute (https://docs.databricks.com/aws/en/dev-tools/bundles/workspace, read 2026-10-17).

## A new developer (Fay)

1. **Link GitHub, once.** Settings, Linked accounts, GitHub.
2. **Create a Git folder for the repo.** Workspace, Create, Git folder, with the repository URL. Then make a branch
   in the Git folder dialog.
3. **Open `databricks.yml`.** Select the deployments icon and the `dev` target, then Deploy.
   - Development mode gives every developer their own schemas, jobs and pipeline, prefixed with their user name
     (`dev_<user>_`), with schedules paused, so two developers never touch each other's objects.
   - A deployment runs as the person deploying.
4. **Run what you changed** from the Bundle resources pane. The pipeline, a job and a dashboard are each one click.
5. **Commit and push** from the Git folder dialog, then open a pull request on GitHub.

The time from step 2 to a first deployed dev target is the onboarding measure (T07).

## Who can deploy what

| Target | Deployed by | Runs as |
|---|---|---|
| `dev` | any developer (meridian-de), into their own prefixed objects | the developer |
| `staging` | an admin (meridian-admin), to test a branch with the integration job | the release principal `meridian-ci` |
| `prod` | an admin, after the integration job passes on staging | the release principal `meridian-ci` |

Developers can view staging and prod deployments but cannot change them. Everything there runs as `meridian-ci`,
so no person needs write access to prod data.
