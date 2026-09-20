import { describe, expect, it } from "vitest";

import { shouldDropSupersededEditDelta } from "./useSessionDetailStream";

describe("edit-resubmit stream guard", () => {
  it("drops queued deltas for the superseded assistant turn only", () => {
    const protection = {
      targetMessageId: "s-message-3",
      clientSubmissionId: "submission-edit-1",
      supersededTurnId: "turn-old-2",
    };

    expect(shouldDropSupersededEditDelta(protection, "turn-old-2")).toBe(true);
    expect(shouldDropSupersededEditDelta(protection, "turn-new-3")).toBe(false);
    expect(shouldDropSupersededEditDelta(protection, undefined)).toBe(false);
  });
});
