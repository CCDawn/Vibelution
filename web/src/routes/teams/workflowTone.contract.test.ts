import { describe, expect, it } from "vitest";

import routeSource from "../TeamsRoute.tsx?raw";
import toneSource from "./workflowTone.ts?raw";

describe("workflow tone helpers contract", () => {
  it("owns quality and ingestion tone mapping", () => {
    expect(toneSource).toContain("export function workflowQualityTone");
    expect(toneSource).toContain("export function workflowIngestionTone");
    expect(toneSource).toContain("workflowTagReady");
  });

  it("is bound from TeamsRoute without inline mapping bodies", () => {
    expect(routeSource).toContain('from "./teams/workflowTone"');
    expect(routeSource).toContain("workflowQualityToneBound");
    expect(routeSource).toContain("workflowIngestionToneBound");
    expect(routeSource).not.toContain("normalized.includes(\"prefiltered\")");
  });
});
