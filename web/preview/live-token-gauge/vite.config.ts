import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  plugins: [{ name: "token-gauge-isolated-acceptance", configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (!new URL(req.url || "/", "http://localhost").pathname.startsWith("/api/")) return next();
      res.statusCode = 403;
      res.end("Isolated simulated stream; no runtime access.");
    });
  }}],
  cacheDir: join(tmpdir(), "vibelution-live-token-gauge", "cache"),
  server: { host: "127.0.0.1", port: 5219, strictPort: true, open: false },
  build: { outDir: join(tmpdir(), "vibelution-live-token-gauge", "dist"), emptyOutDir: true,
    rollupOptions: { input: "preview/live-token-gauge/index.html" } },
});
if (config.server) config.server.proxy = {};
export default defineConfig(config);
