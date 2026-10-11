// Isolated documentation entry. No backend, model, or operator config is read.
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { resolve, join } from "node:path";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";

const projectRoot = fileURLToPath(new URL("../../../", import.meta.url));
const require = createRequire(resolve(projectRoot, "web/package.json"));
const { default: react } = await import(pathToFileURL(require.resolve("@vitejs/plugin-react")).href);
const { default: tailwindcss } = await import(pathToFileURL(require.resolve("@tailwindcss/vite")).href);
const dependencies = ["react", "react/jsx-runtime", "react/jsx-dev-runtime", "react-dom", "react-dom/client", "@tanstack/react-query"];
const cacheId = createHash("sha256").update(projectRoot).digest("hex").slice(0, 12);

export default {
  root: projectRoot,
  cacheDir: join(tmpdir(), "vibelution-readme-preview", cacheId),
  define: { __VIBELUTION_BUILD_ID__: JSON.stringify("readme-example") },
  plugins: [
    {
      name: "readme-deny-runtime",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (String(req.url || "").startsWith("/api/")) {
            res.statusCode = 403;
            res.setHeader("Content-Type", "application/json");
            res.end("{}");
            return;
          }
          next();
        });
      },
    },
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: [
      ...dependencies.map((name) => ({ find: new RegExp("^" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$"), replacement: require.resolve(name) })),
      { find: "@radix-ui/react-compose-refs", replacement: resolve(projectRoot, "web/src/vendor/radixComposeRefs.ts") },
    ],
  },
  optimizeDeps: { exclude: ["@radix-ui/react-compose-refs"] },
  server: { host: "127.0.0.1", port: 5188, strictPort: true, open: false, proxy: {}, fs: { allow: [projectRoot] } },
};
