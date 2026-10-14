import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  root: fileURLToPath(new URL(".", import.meta.url)),
  cacheDir: join(tmpdir(), "vibelution-companion-life-immersion", "vite-cache"),
  build: {
    rolldownOptions: { input: { index: fileURLToPath(new URL("./index.html", import.meta.url)) } },
  },
  plugins: [{
    name: "isolated-companion-life-preview",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith("/api/")) {
          res.statusCode = 404;
          res.end("Isolated design preview");
          return;
        }
        next();
      });
    },
  }],
  server: { host: "127.0.0.1", strictPort: true, open: false },
});
if (config.server) config.server.proxy = {};
export default defineConfig(config);
