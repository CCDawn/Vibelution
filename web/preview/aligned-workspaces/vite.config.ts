import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";
import { workspaceFixtures } from "./fixtures";
const config = mergeConfig(base, {
  plugins: [{ name: "aligned-workspaces-read-only", configureServer(server) {
    server.middlewares.use((req, res, next) => {
      const path = new URL(req.url || "/", "http://localhost").pathname;
      if (!path.startsWith("/api/")) return next();
      const data = req.method === "GET" ? workspaceFixtures[path] : undefined;
      res.statusCode = data === undefined ? 403 : 200;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(data ?? { detail: "隔离验收不执行真实工具、模型调用、保存、删除或权限变更。" }));
    });
  }}],
  cacheDir: join(tmpdir(), "vibelution-aligned-workspaces", "cache"),
  server: { host: "127.0.0.1", port: 5219, strictPort: true, open: false },
  build: { outDir: join(tmpdir(), "vibelution-aligned-workspaces", "dist"), emptyOutDir: true, rollupOptions: { input: "preview/aligned-workspaces/index.html" } },
});
if (config.server) config.server.proxy = {};
export default defineConfig(config);
