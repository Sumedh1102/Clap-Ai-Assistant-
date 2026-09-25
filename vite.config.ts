import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The CLAP HUD lives in web/frontend and is built into web/frontend/dist,
// which Flask serves at http://127.0.0.1:7777. During `npm run dev`, API and
// event-stream requests are proxied to the running CLAP backend.
const backend = `http://127.0.0.1:${process.env.WEB_PORT ?? "7777"}`;

export default defineConfig({
  root: fileURLToPath(new URL("./web/frontend", import.meta.url)),
  plugins: [react()],
  resolve: {
    alias: [
      // `import { PredictiveArcCanvas } from "@designcodeio/threeui"` resolves to the
      // package's own per-component entry (exports "./components/*"), which re-exports
      // the same registered shaders/predictive-arc module. This keeps the rest of the
      // library — including components that bundle other Three.js builds — out of the
      // dev server's pre-bundle. Exact match only: the style.css import is unaffected.
      {
        find: /^@designcodeio\/threeui$/,
        replacement: "@designcodeio/threeui/components/PredictiveArcCanvas",
      },
    ],
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // The package's other Predictive Arc variants (Neuform, ribbon) are split into
    // lazy chunks that are only fetched if selected; CLAP uses "predictive" only.
    chunkSizeWarningLimit: 600,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend },
    },
  },
});
