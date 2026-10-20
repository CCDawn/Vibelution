import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  cacheDir: join(tmpdir(), "vibelution-finance-investment-preview", "vite-cache"),
  plugins: [{
    name: "investment-preview-entry",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === "/" || req.url === "/index.html") {
          res.writeHead(302, { Location: "/preview/finance-investment-plan/index.html" });
          res.end();
        } else if (req.url?.startsWith("/api/")) {
          res.writeHead(403); res.end("Preview has no product API access.");
        } else next();
      });
    },
  }],
  server: { host: "127.0.0.1", port: 5208, strictPort: true, open: false },
});
if (config.server) config.server.proxy = {};
export default defineConfig(config);
