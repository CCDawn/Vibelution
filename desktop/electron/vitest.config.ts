import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    // Native host/Job and filesystem suites also spawn real child processes.
    maxWorkers: 4,
    include: ["tests/**/*.test.ts"]
  }
});
