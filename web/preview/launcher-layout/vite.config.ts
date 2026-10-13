import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { tmpdir } from "node:os";

const directory = fileURLToPath(new URL(".", import.meta.url));
export default defineConfig({
  root: directory,
  cacheDir: resolve(tmpdir(), "vibelution-launcher-layout-preview", "vite-cache"),
  plugins: [react(), tailwindcss(), {
    name: "isolated-launcher-preview",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith("/api/")) {
          res.statusCode = 404;
          res.end("This preview has no product API connection.");
          return;
        }
        next();
      });
    },
  }],
  server: { host: "127.0.0.1", port: 5198, strictPort: true, open: false, fs: { allow: [resolve(directory, "../.."), resolve(directory, "../../node_modules")] } },
  build: { outDir: resolve(tmpdir(), "vibelution-launcher-layout-preview", "dist"), emptyOutDir: false },
});
