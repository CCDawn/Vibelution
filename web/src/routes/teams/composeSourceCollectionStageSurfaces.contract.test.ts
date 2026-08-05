import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const scSource = readFileSync(new URL("./useTeamsScComposition.ts", import.meta.url), "utf8");
const composeSource = readFileSync(new URL("./composeSourceCollectionStageSurfaces.ts", import.meta.url), "utf8");

describe("composeSourceCollectionStageSurfaces R2-k contract", () => {
  it("owns stage advance, stage modules, board chrome, and SC controller", () => {
    expect(composeSource).toContain("export function composeSourceCollectionStageSurfaces");
    expect(composeSource).toContain("createSourceCollectionStageAdvance({");
    expect(composeSource).toContain("buildSourceCollectionStageModules({");
    expect(composeSource).toContain("buildSourceCollectionBoardChrome({");
    expect(composeSource).toContain("createSourceCollectionController({");
  });

  it("is the only place SC composition builds stage surfaces", () => {
    expect(scSource).toContain("composeSourceCollectionStageSurfaces({");
    expect(scSource).not.toContain("createSourceCollectionStageAdvance({");
    expect(scSource).not.toContain("buildSourceCollectionStageModules({");
    expect(scSource).not.toContain("createSourceCollectionController({");
  });
});
