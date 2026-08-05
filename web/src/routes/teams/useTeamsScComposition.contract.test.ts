import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const scSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const modelSource = readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchScLayer.ts", import.meta.url), "utf8");

describe("useTeamsScComposition R2-o/p debt cleanup", () => {
  it("picks presentation/stage keys instead of flat re-list", () => {
    expect(scSource).toContain("function pickCtx");
    expect(scSource).toContain("PRESENTATION_CTX_KEYS");
    expect(scSource).toContain("STAGE_SHELL_CTX_KEYS");
    expect(scSource).toContain("...presentation");
    expect(scSource).toContain("...stageSurfaces");
    expect(scSource).not.toContain("sourceCollectionProjectedCollectedCountText,");
  });

  it("is mounted from workbench SC layer once", () => {
    expect(modelSource).toContain("useTeamsScComposition({");
    expect(modelSource.match(/useTeamsScComposition\(/g) ?? []).toHaveLength(1);
    expect(modelSource).toContain("useTeamsWorkbenchScLayer");
  });
});
