import { describe, expect, it } from "vitest";

import currentTaskStyles from "./ResearchCurrentTaskInspector.styles";
import nodeInspectorStyles from "./HypothesisFirstNodeInspector.styles";

describe("hypothesis-first inspector scroll ownership", () => {
  it("keeps the current-task body as the only vertical scroll owner", () => {
    expect(currentTaskStyles.body).toContain("min-h-0");
    expect(currentTaskStyles.body).toContain("overflow-auto");
    expect(nodeInspectorStyles.panel).not.toContain("h-full");
    expect(nodeInspectorStyles.panel).not.toContain("overflow-auto");
  });
});
