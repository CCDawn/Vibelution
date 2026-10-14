import { defineConfig, mergeConfig } from "vite";
import { tmpdir } from "node:os";
import { join } from "node:path";
import base from "../../vite.config.ts";

const config = mergeConfig(base, {
  cacheDir: join(tmpdir(), "vibelution-finance-desktop-tabs", "vite-cache"),
  server: { host: "127.0.0.1", port: 5187, strictPort: true, open: false },
});
// Preview requests never reach the product backend.
if (config.server) config.server.proxy = {};
export default defineConfig(config);
