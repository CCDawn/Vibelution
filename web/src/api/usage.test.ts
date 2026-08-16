import { describe, expect, it } from "vitest";

import apiSource from "./usage.ts?raw";
import routeSource from "../routes/UsageRoute.tsx?raw";

describe("usage catalog API", () => {
  it("owns usage summary transport", () => {
    expect(apiSource).toContain("export function fetchUsageSummary");
    expect(apiSource).toContain('"/api/usage/summary"');
  });

  it("keeps UsageRoute free of usage JSON paths", () => {
    expect(routeSource).toContain("fetchUsageSummary(");
    expect(routeSource).not.toContain("/api/usage/");
  });
});
