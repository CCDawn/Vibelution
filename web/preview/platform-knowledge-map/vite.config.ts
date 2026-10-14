import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config";

const config = mergeConfig(base, {
  cacheDir: join(tmpdir(), "vibelution-platform-knowledge-map", "vite-cache"),
  server: { host: "127.0.0.1", port: 0, strictPort: false, open: false },
});
if (config.server) config.server.proxy = {};
export default defineConfig(config);
