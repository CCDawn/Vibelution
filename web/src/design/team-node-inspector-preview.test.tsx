/** @vitest-environment happy-dom */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { TeamNodeInspectorPreviewApp } from "./team-node-inspector-preview";

describe("team node inspector preview", () => {
  it("puts the current model and budget meters in the proposed inspector", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <TeamNodeInspectorPreviewApp />
      </VuiProvider>,
    );
    expect(markup).toContain("qwen-plus");
    expect(markup).toContain("Tokens");
    expect(markup).toContain('data-testid="model-trigger"');
    expect(markup).toContain("source_ingestor");
    expect(markup).toContain("建议");
  });
});
