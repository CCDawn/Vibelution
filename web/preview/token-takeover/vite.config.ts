import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

// Isolated preview entry. Independent of web/vite.config.ts on purpose:
// this preview must never scan or affect the production app graph.
export default defineConfig({
  plugins: [tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5185,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 5186,
    strictPort: true,
  },
});
