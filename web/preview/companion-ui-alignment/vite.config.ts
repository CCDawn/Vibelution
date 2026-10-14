import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  cacheDir: join(tmpdir(), "vibelution-companion-ui-alignment", "vite-cache"),
  plugins: [{ name: "isolated-companion-preview", configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.url?.startsWith("/api/")) { res.statusCode = 404; res.end("Isolated preview"); return; }
      next();
    });
  }}],
  server: { host: "127.0.0.1", strictPort: true, open: false },
});
if (config.server) config.server.proxy = {};
export default defineConfig(config);
