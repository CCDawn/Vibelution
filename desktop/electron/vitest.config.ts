import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    // Native Job/listener suites can reuse just-closed ephemeral ports across
    // files. Keep their OS resources exclusive without relaxing deadlines.
    fileParallelism: false,
    include: ["tests/**/*.test.ts"]
  }
});
