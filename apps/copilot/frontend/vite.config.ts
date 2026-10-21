import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes into the copilot app's runtime/static, which runtime/ui.py serves at / and /assets.
// `npm run dev` proxies the API to a copilot server running locally on port 8000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../runtime/static", emptyOutDir: true, chunkSizeWarningLimit: 1600 },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
