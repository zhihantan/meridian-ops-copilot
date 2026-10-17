# UI-only steps

Steps with no working API path in this workspace, with the date each was done. Everything else is code.

| Date | Step | Why it is manual | Who |
|---|---|---|---|
| 2026-10-15 | Create catalogs `meridian_dev`, `meridian_staging`, `meridian` with default storage | Catalogs API returns "Please use the UI to create a catalog with Default Storage" | Fay (workspace admin) |
| 2026-10-17 | Link GitHub in user settings, then create a Git folder for the repo | Git credentials are personal and are linked in the UI | Fay, Eli |
| 2026-10-17 | Deploy `dev`, `staging` or `prod` from a Git folder, and run jobs from the Bundle resources pane | Bundles in the workspace are driven from the UI. The same deployment from the CLI is `databricks bundle deploy -t <target>` | Fay (dev), Eli (staging, prod) |
