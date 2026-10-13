import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  cacheDir: join(tmpdir(), "vibelution-team-layout-preview", "vite-cache"),
  optimizeDeps: { entries: ["preview/team-layout/index.html"] },
  plugins: [{
    name: "team-layout-preview-isolation",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split("?")[0] === "/") {
          res.writeHead(302, { Location: "/preview/team-layout/index.html" });
          res.end();
          return;
        }
        if (req.url?.startsWith("/api/")) {
          res.writeHead(404);
          res.end("Isolated preview: no product API");
          return;
        }
        next();
      });
    },
  }],
  server: { host: "127.0.0.1", port: 5206, strictPort: true, open: false },
});
if (config.server) config.server.proxy = {};
export default defineConfig(config);
