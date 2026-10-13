import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  root: fileURLToPath(new URL("../../", import.meta.url)),
  cacheDir: process.env.VIBELUTION_PREVIEW_CACHE,
  plugins: [react(), tailwindcss(), {
    name: "preview-api-boundary",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (String(req.url).startsWith("/api/")) { res.statusCode = 403; res.end("No live API in design preview"); return; }
        next();
      });
    },
  }],
  resolve: { alias: { "@radix-ui/react-compose-refs": fileURLToPath(new URL("../../src/vendor/radixComposeRefs.ts", import.meta.url)) } },
  server: { host: "127.0.0.1", strictPort: true, open: false },
});
