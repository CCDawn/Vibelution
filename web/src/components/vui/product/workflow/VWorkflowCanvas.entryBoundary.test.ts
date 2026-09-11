import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The canvas renderer statically imports ``@xyflow/react`` plus its stylesheet, which
 * makes the whole module graph behind it non-tree-shakeable. The facade therefore has
 * to reach it through a dynamic import: a static re-export here puts the canvas engine
 * (xyflow + its d3 stack, ~430 KB of source) back into the eager application entry for
 * every route that touches the VUI barrel. `npm run check:bundle` catches the size
 * symptom; this pins the cause.
 */
const facadeSource = readFileSync(resolve(import.meta.dirname, "VWorkflowCanvas.tsx"), "utf8");

const RENDERER_SPECIFIER = "../../renderers/shadcn/ShadcnWorkflowCanvas";

describe("VWorkflowCanvas entry boundary", () => {
  it("loads the xyflow renderer through a dynamic import", () => {
    expect(facadeSource).toContain(`await import("${RENDERER_SPECIFIER}")`);
    expect(facadeSource).toContain("lazy(");
    expect(facadeSource).toContain("Suspense");
  });

  it("never imports the xyflow renderer statically", () => {
    const staticImport = new RegExp(`import\\s+\\{[^}]*\\}\\s+from\\s+["']${RENDERER_SPECIFIER}["']`);
    expect(facadeSource).not.toMatch(staticImport);
    // The type-only import is erased at build time and stays allowed.
    expect(facadeSource).toContain(`import type { ShadcnWorkflowCanvasProps } from "${RENDERER_SPECIFIER}"`);
  });

  it("keeps the public prop surface identical to the renderer props", () => {
    expect(facadeSource).toContain("export type VWorkflowCanvasProps = ShadcnWorkflowCanvasProps");
  });
});
