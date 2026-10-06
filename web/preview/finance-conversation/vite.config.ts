import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";

const previewConfig = mergeConfig(base, {
  cacheDir: join(tmpdir(), "vibelution-finance-conversation-preview", "vite-cache"),
  plugins: [{
    name: "finance-conversation-preview-entry",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === "/" || req.url === "/index.html") {
          res.statusCode = 302;
          res.setHeader("Location", "/preview/finance-conversation/index.html");
          res.end();
          return;
        }
        next();
      });
    },
  }],
  server: { host: "127.0.0.1", port: 5186, strictPort: true, open: false },
});
// No preview request is forwarded to the product backend.
if (previewConfig.server) previewConfig.server.proxy = {};
export default defineConfig(previewConfig);
