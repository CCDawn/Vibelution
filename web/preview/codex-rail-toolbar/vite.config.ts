import { defineConfig, mergeConfig } from "vite";
import baseConfig from "../../vite.config";
export default defineConfig(mergeConfig(baseConfig, { server: { host: "127.0.0.1", port: 50924, strictPort: true, open: false }, build: { rollupOptions: { input: "codex-rail-toolbar-preview.html" } } }));
