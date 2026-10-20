import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
export default defineConfig({
  root: fileURLToPath(new URL("../..", import.meta.url)), plugins: [react(), tailwindcss()],
  resolve: { alias: { "@radix-ui/react-compose-refs": fileURLToPath(new URL("../../src/vendor/radixComposeRefs.ts", import.meta.url)) } },
  server: { host: "127.0.0.1", open: false, strictPort: true },
  build: { outDir: fileURLToPath(new URL("./dist", import.meta.url)), rollupOptions: { input: fileURLToPath(new URL("./index.html", import.meta.url)) } },
});
