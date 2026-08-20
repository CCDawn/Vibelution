import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("design preview vite config", () => {
  it("redirects the workbench root to the team conversation stream preview", () => {
    const source = readFileSync(resolve(import.meta.dirname, "../../vite.design-preview.config.ts"), "utf8");
    expect(source).toContain("/team-conversation-stream-preview.html");
    expect(source).toContain("design-preview-root-redirect");
    expect(source).toContain('path === "/"');
  });
});
