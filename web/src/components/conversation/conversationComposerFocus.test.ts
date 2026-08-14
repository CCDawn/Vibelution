import { describe, expect, it } from "vitest";

import { shouldApplyComposerFocusRequest } from "./conversationComposerFocus";

describe("shouldApplyComposerFocusRequest", () => {
  it("applies a new enabled request when document focus is unowned", () => {
    expect(shouldApplyComposerFocusRequest({
      composerDisabled: false,
      focusSignal: "delete:session-b:1",
      hasCompetingFocus: false,
      lastAppliedFocusSignal: "",
    })).toBe(true);
  });

  it("does not replay requests or steal focus from another control", () => {
    expect(shouldApplyComposerFocusRequest({
      composerDisabled: false,
      focusSignal: "delete:session-b:1",
      hasCompetingFocus: false,
      lastAppliedFocusSignal: "delete:session-b:1",
    })).toBe(false);
    expect(shouldApplyComposerFocusRequest({
      composerDisabled: false,
      focusSignal: "delete:session-b:2",
      hasCompetingFocus: true,
      lastAppliedFocusSignal: "delete:session-b:1",
    })).toBe(false);
  });

  it("defers an empty or disabled request", () => {
    expect(shouldApplyComposerFocusRequest({
      composerDisabled: false,
      focusSignal: "",
      hasCompetingFocus: false,
      lastAppliedFocusSignal: "",
    })).toBe(false);
    expect(shouldApplyComposerFocusRequest({
      composerDisabled: true,
      focusSignal: "delete:session-b:1",
      hasCompetingFocus: false,
      lastAppliedFocusSignal: "",
    })).toBe(false);
  });
});
