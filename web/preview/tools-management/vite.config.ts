import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  cacheDir: join(tmpdir(), "vibelution-tools-management-preview", "cache"),
  server: { host: "127.0.0.1", port: 5218, strictPort: true, open: false },
  build: { outDir: join(tmpdir(), "vibelution-tools-management-preview", "dist"), emptyOutDir: true, rollupOptions: { input: "preview/tools-management/index.html" } },
});
// This preview has no product API calls or backend proxy.
if (config.server) config.server.proxy = {};
export default defineConfig(config);
