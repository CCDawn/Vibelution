import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeStyles = readFileSync(new URL("./src/routes/MemoryRoute.legacy.css", import.meta.url), "utf-8");

describe("MemoryRoute CSS layout contract", () => {
  it("clips long memory list text so raw HTML summaries cannot overlap cards", () => {
    expect(routeStyles).toContain(".itemButton");
    expect(routeStyles).toContain("overflow: hidden;");
    expect(routeStyles).toContain(".itemContentButton");
    expect(routeStyles).toContain(".sourceCopy span,");
    expect(routeStyles).toContain(".itemPath,");
    expect(routeStyles).toContain(".itemSummary");
    expect(routeStyles).toContain("display: block;");
    expect(routeStyles).toContain("text-overflow: ellipsis;");
  });
});
