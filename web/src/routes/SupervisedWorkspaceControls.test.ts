import { describe, expect, it } from "vitest";

import { getEffectiveIntakeMode } from "./SupervisedWorkspaceControls";

describe("supervised workspace controls", () => {
  it("prefers auto when the overview reports auto mode", () => {
    expect(getEffectiveIntakeMode("auto", "manual_review")).toBe("auto");
  });

  it("falls back to config auto mode when overview mode is absent", () => {
    expect(getEffectiveIntakeMode(null, "auto")).toBe("auto");
  });

  it("defaults to manual review when neither source reports auto mode", () => {
    expect(getEffectiveIntakeMode(undefined, undefined)).toBe("manual_review");
  });
});
