import { describe, expect, it } from "vitest";

import routeShellSource from "./TeamsRouteWorkbench.tsx?raw";
import routeModelSourceThin from "./useTeamsWorkbenchModel.tsx?raw";
import routeFoundationSource from "./useTeamsWorkbenchFoundation.tsx?raw";
import routeShellPhaseSource from "./useTeamsWorkbenchShellPhase.tsx?raw";
const routeModelSource = `${routeModelSourceThin}\n${routeFoundationSource}\n${routeShellPhaseSource}`;
import chromeSource from "./teamsWorkbenchChrome.ts?raw";
const routeSource = `${routeShellSource}\n${routeModelSource}\n${chromeSource}`;
import toneSource from "./workflowTone.ts?raw";

describe("workflow tone helpers contract", () => {
  it("owns quality and ingestion tone mapping", () => {
    expect(toneSource).toContain("export function workflowQualityTone");
    expect(toneSource).toContain("export function workflowIngestionTone");
    expect(toneSource).toContain("workflowTagReady");
  });

  it("is bound from TeamsRoute without inline mapping bodies", () => {
    // Chrome owns the workflowTone import + bound helpers; model consumes the bindings.
    expect(chromeSource).toMatch(/from ["']\.\/workflowTone["']/);
    expect(routeSource).toContain("workflowQualityToneBound");
    expect(routeSource).toContain("workflowIngestionToneBound");
    expect(routeSource).not.toContain("normalized.includes(\"prefiltered\")");
  });
});
