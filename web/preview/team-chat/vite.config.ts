import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  cacheDir: join(tmpdir(), "vibelution-team-chat-preview-20261010", "vite-cache"),
  plugins: [{
    name: "team-chat-preview-entry",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split("?")[0] === "/" || req.url?.split("?")[0] === "/index.html") {
          res.statusCode = 302;
          res.setHeader("Location", `/preview/team-chat/index.html${req.url.includes("?") ? req.url.slice(req.url.indexOf("?")) : ""}`);
          res.end();
          return;
        }
        if (req.url?.startsWith("/api/")) {
          res.statusCode = 404;
          res.end("Isolated design preview");
          return;
        }
        next();
      });
    },
  }],
  server: { host: "127.0.0.1", port: 5192, strictPort: true, open: false },
});
// Preview traffic must never be forwarded to the shared product backend.
if (config.server) config.server.proxy = {};
export default defineConfig(config);
