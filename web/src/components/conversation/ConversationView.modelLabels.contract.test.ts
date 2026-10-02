import { describe, expect, it } from "vitest";

import viewSource from "./ConversationView.tsx?raw";

describe("ConversationView model labels source contract", () => {
  it("derives model labels from the lightweight public config summary", () => {
    expect(viewSource).toContain("queryKeys.configPublic()");
    expect(viewSource).toContain("fetchPublicConfig(");
    expect(viewSource).toContain("modelLabels");
  });

  it("never mounts the heavy config workspace query for labels", () => {
    expect(viewSource).not.toContain("queryKeys.configWorkspace()");
    expect(viewSource).not.toContain("fetchConfigWorkspace(");
  });

  it("keeps the raw-model-id degradation for absent labels", () => {
    expect(viewSource).toContain(
      "modelLabelByModelId.get(modelId) ?? modelId",
    );
  });
});
