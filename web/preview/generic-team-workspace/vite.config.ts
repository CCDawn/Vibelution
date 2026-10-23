import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { join } from "node:path";

export default defineConfig({
  root: fileURLToPath(new URL("../..", import.meta.url)),
  plugins: [react(), tailwindcss(), {
    name: "generic-team-preview-no-backend",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!(req.url || "").startsWith("/api/")) return next();
        res.statusCode = 403;
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ detail: "隔离预览不连接产品 API。" }));
      });
    },
  }],
  resolve: { dedupe: ["react", "react-dom"], alias: { "@radix-ui/react-compose-refs": fileURLToPath(new URL("../../src/vendor/radixComposeRefs.ts", import.meta.url)) } },
  cacheDir: join(tmpdir(), "vibelution-compact-team-preview", "vite-cache"),
  server: { host: "127.0.0.1", port: 5237, strictPort: true, open: false },
  build: { outDir: join(tmpdir(), "vibelution-compact-team-preview", "dist"), emptyOutDir: false, rollupOptions: { input: fileURLToPath(new URL("./index.html", import.meta.url)) } },
});
