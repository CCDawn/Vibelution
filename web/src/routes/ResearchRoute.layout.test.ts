import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(resolve(import.meta.dirname, "ResearchRoute.tsx"), "utf8");
const routerSource = readFileSync(resolve(import.meta.dirname, "../app/router.tsx"), "utf8");

describe("ResearchRoute retired contract", () => {
  it("is a redirect shell and is not mounted by router", () => {
    expect(routeSource).toContain("export function ResearchRoute");
    expect(routeSource).toContain("resolveLegacyResearchLocation");
    expect(routeSource).toContain("Navigate");
    expect(routerSource).not.toContain("ResearchRoute");
    expect(routerSource).toContain('path: "research"');
    expect(routerSource).toContain("LegacyTeamsRedirect");
  });
});
