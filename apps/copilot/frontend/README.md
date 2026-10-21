# Meridian Ops console (BUILD)

The copilot app's browser UI: React, TypeScript, Vite and Tailwind CSS, with Recharts for Genie's charts. The
copilot's FastAPI server serves the build at `/` (`runtime/ui.py`), and every API call runs as the signed-in visitor.

- `npm run build` writes the app to `../runtime/static`; `scripts/build_copilot.sh` runs it before each deploy.
- `npm run dev` serves the UI with hot reload and proxies `/api` to a copilot server on `127.0.0.1:8000`.
- `src/pages`: Overview, Ops Copilot, Genie, Knowledge and Approvals. `src/components`: the shared pieces.

Model output is rendered as markdown with raw HTML disabled, and links are shown as plain text.
