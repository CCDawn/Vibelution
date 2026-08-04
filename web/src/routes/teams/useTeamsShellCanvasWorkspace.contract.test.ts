import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const hookSource = readFileSync(new URL("./useTeamsShellCanvasWorkspace.ts", import.meta.url), "utf8");

describe("useTeamsShellCanvasWorkspace Phase 3 contract", () => {
  it("TeamsRoute consumes shell + canvas projection hooks and no longer declares shell/canvas useState", () => {
    expect(routeSource).toContain("useTeamsShellCanvasWorkspace({");
    expect(routeSource).toContain("useTeamsCanvasProjection({");
    expect(routeSource).not.toContain('const [selectedTeamId, setSelectedTeamId] = useState("")');
    expect(routeSource).not.toContain("const [teamShellMode, setTeamShellMode] = useState");
    expect(routeSource).not.toContain("const [nodePositionDrafts, setNodePositionDrafts] = useState");
    expect(routeSource).not.toContain("const teamCanvasQuery = useQuery({");
    expect(routeSource).not.toContain("const durableCanvas = canvasFromTeamOrFallback");
  });

  it("hook module owns shell state, canvas query gate, and display projection", () => {
    expect(hookSource).toContain("export function useTeamsShellCanvasWorkspace");
    expect(hookSource).toContain("export function useTeamsCanvasProjection");
    expect(hookSource).toContain("resolveTeamCanvasQueryEnabled");
    expect(hookSource).toContain("autoLayoutResearchCanvasNodes");
    expect(hookSource).toContain("canvasFromTeamOrFallback");
    expect(hookSource).toContain("setNodePositionDrafts");
  });
});
