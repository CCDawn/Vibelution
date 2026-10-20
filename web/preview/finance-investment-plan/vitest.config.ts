import { defineConfig } from "vitest/config";
export default defineConfig({
  test: { environment: "node", include: ["preview/finance-investment-plan/model.test.ts"] },
});
