import { describe, expect, it } from "vitest";

import { createVuiStyleMap } from "./styles/createVuiStyleMap";

function classWords(className: string): Set<string> {
  return new Set(className.split(/\s+/).filter(Boolean));
}

describe("VUI automatic style map contract", () => {
  it("does not infer compact control geometry from status or lifecycle container names", () => {
    const styles = createVuiStyleMap(
      [
        "statusCluster",
        "statusGuidePanel",
        "statusGuideCard",
        "statusGuideListItem",
        "tabStrip",
        "lifecycleProofCard",
        "lifecycleProofItem",
      ] as const,
      { includeKeyClass: false },
    );

    for (const key of [
      "statusCluster",
      "statusGuidePanel",
      "statusGuideCard",
      "statusGuideListItem",
      "tabStrip",
      "lifecycleProofCard",
      "lifecycleProofItem",
    ] as const) {
      const words = classWords(styles[key]);
      expect(words.has("inline-flex"), key).toBe(false);
      expect(words.has("w-fit"), key).toBe(false);
      expect(words.has("rounded-full"), key).toBe(false);
    }
  });

  it("keeps pill geometry opt-in through explicit pill badge chip or tag names", () => {
    const styles = createVuiStyleMap(
      ["modelChip", "unreadBadge", "versionPill", "sourceTag"] as const,
      { includeKeyClass: false },
    );

    for (const key of ["modelChip", "unreadBadge", "versionPill", "sourceTag"] as const) {
      const words = classWords(styles[key]);
      expect(words.has("inline-flex"), key).toBe(true);
      expect(words.has("w-fit"), key).toBe(true);
      expect(words.has("rounded-full"), key).toBe(true);
    }
  });

  it("keeps button geometry opt-in through explicit button trigger or tab names", () => {
    const styles = createVuiStyleMap(
      ["actionButton", "utilityTrigger", "agentTab"] as const,
      { includeKeyClass: false },
    );

    for (const key of ["actionButton", "utilityTrigger", "agentTab"] as const) {
      const words = classWords(styles[key]);
      expect(words.has("inline-flex"), key).toBe(true);
      expect(words.has("w-fit"), key).toBe(true);
      expect(words.has("rounded-[var(--radius-control)]"), key).toBe(true);
    }
  });
});
