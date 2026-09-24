import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

/**
 * Isolated preview entry. Lives under web/preview/chat-stream-core/ and is
 * NOT part of the production web/ build graph (web/tsconfig does not include
 * this directory; the production router does not reference it).
 *
 * `server.fs.allow` whitelists the worktree web/ directory so the preview can
 * import pure logic modules from web/src (codexStreamController,
 * streamingMarkdown, conversationTimelineFollowState, conversationHistoryWindow)
 * without modifying them. The tailwind plugin powers the runtime scene
 * (runtime-scene.html), which mounts the real ConversationView with the
 * production stylesheet chain.
 */
export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: 5199,
    strictPort: true,
    fs: {
      allow: [fileURLToPath(new URL("../../", import.meta.url))],
    },
  },
});
