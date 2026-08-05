import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const core = readFileSync(new URL("../useSourceCollectionPresentationCore.ts", import.meta.url), "utf8");
const pipeline = readFileSync(new URL("../useSourceCollectionPresentationPipeline.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationMid.ts", import.meta.url), "utf8") + "\n" + readFileSync(new URL("../useSourceCollectionPresentationTail.ts", import.meta.url), "utf8");
const body = `${core}\n${pipeline}`;
const flags = readFileSync(new URL("./deriveSourceCollectionOperationFlags.ts", import.meta.url), "utf8");
const ctx = readFileSync(new URL("./SourceCollectionPresentationContext.tsx", import.meta.url), "utf8");
const controller = readFileSync(new URL("./createSourceCollectionController.tsx", import.meta.url), "utf8");

describe("R2-q presentation debt cleanup", () => {
  it("owns operation flags pure and uses them from presentation core", () => {
    expect(flags).toContain("export function deriveSourceCollectionOperationFlags");
    expect(body).toContain("deriveSourceCollectionOperationFlags({");
    expect(body).not.toContain("const sourceCollectionAcceptedBackgroundActive = Boolean(");
    expect(core).toContain("useSourceCollectionPresentationPipeline");
  });

  it("provides SC presentation context from controller standalone page", () => {
    expect(ctx).toContain("SourceCollectionPresentationProvider");
    expect(controller).toContain("SourceCollectionPresentationProvider");
  });
});
