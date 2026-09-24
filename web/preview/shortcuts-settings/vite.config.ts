/**
 * 预览专用 vite 配置 —— root 指向 web/（让 /src 的真实组件、shortcuts 纯逻辑与
 * 设计样式可解析），端口 5198，服务本预览页；不进生产构建（生产 vite.config.ts
 * 的 input 不含本页，生产 tsconfig/vitest 也不扫描 preview 目录）。
 */
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const previewDir = fileURLToPath(new URL(".", import.meta.url));
const webRoot = resolve(previewDir, "..", "..");
const radixComposeRefsEntry = resolve(webRoot, "src/vendor/radixComposeRefs.ts");
const PREVIEW_PATH = "/preview/shortcuts-settings/index.html";

export default defineConfig({
  root: webRoot,
  plugins: [
    {
      // 根路径重定向到预览页，避免误开生产入口。
      name: "shortcuts-settings-preview-root-redirect",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const path = String(req.url ?? "").split("?")[0];
          if (path === "/" || path === "/index.html") {
            res.statusCode = 302;
            res.setHeader("Location", PREVIEW_PATH);
            res.end();
            return;
          }
          next();
        });
      },
    },
    tailwindcss(),
    react(),
  ],
  resolve: {
    alias: {
      // React 19 composed refs 稳定化 shim，与生产 vite.config.ts 同一来源。
      "@radix-ui/react-compose-refs": radixComposeRefsEntry,
    },
  },
  optimizeDeps: {
    exclude: ["@radix-ui/react-compose-refs"],
  },
  server: {
    host: "127.0.0.1",
    port: 5198,
    strictPort: true,
    open: false,
  },
});
