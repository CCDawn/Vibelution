import { defineConfig, mergeConfig } from "vite";

import baseConfig from "./vite.config.ts";

const PREVIEW_PATH = "/team-conversation-stream-preview.html";

function designPreviewRootRedirect() {
  return {
    name: "design-preview-root-redirect",
    configureServer(server: { middlewares: { use: (handler: (req: { url?: string }, res: { statusCode: number; setHeader: (name: string, value: string) => void; end: () => void }, next: () => void) => void) => void } }) {
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
  };
}

export default defineConfig(
  mergeConfig(baseConfig, {
    plugins: [designPreviewRootRedirect()],
    server: {
      host: "127.0.0.1",
      port: 5179,
      strictPort: true,
      open: PREVIEW_PATH,
    },
  }),
);
