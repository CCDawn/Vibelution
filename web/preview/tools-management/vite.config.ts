import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  plugins: [{ name: "tools-read-only-acceptance", configureServer(server) {
    server.middlewares.use((req, res, next) => {
      const path = new URL(req.url || "/", "http://localhost").pathname;
      if (!path.startsWith("/api/")) return next();
      // The actual ToolsRoute uses a readonly local snapshot. Never forward to a runtime.
      let data: unknown;
      if (req.method === "GET" && path === "/api/control-token") data = {header:"X-Vibelution-Control-Token", controlToken:"isolated-readonly-acceptance"};
      else if (req.method === "GET") {
        try { data = JSON.parse(readFileSync(join(tmpdir(), "vibelution-tools-management-preview", "read-only-data.json"), "utf8"))[path]; } catch { /* No snapshot: fail closed. */ }
      }
      res.statusCode = data === undefined ? 403 : 200;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(data ?? {detail:"只读验收不会执行真实工具、保存权限或访问后台服务。"}));
    });
  }}],
  cacheDir: join(tmpdir(), "vibelution-tools-management-preview", "cache"),
  server: { host: "127.0.0.1", port: 5218, strictPort: true, open: false },
  build: { outDir: join(tmpdir(), "vibelution-tools-management-preview", "dist"), emptyOutDir: true, rollupOptions: { input: "preview/tools-management/index.html" } },
});
// This preview has no product API calls or backend proxy.
if (config.server) config.server.proxy = {};
export default defineConfig(config);
