import { describe, expect, it } from "vitest";

import styles from "./chat/ChatStatusRail.styles";

describe("ChatCodingRoute run mode chip visual contract", () => {
  it("keeps persistent enabled state on chip chrome instead of filling the whole chip with accent", () => {
    expect(styles.featureChipActive).toContain("border-[color-mix");
    expect(styles.featureChipActive).toContain("text-[var(--fg-primary)]");
    expect(styles.featureChipActive).not.toContain(" bg-[var(--accent-cool)]");
    expect(styles.featureChipPrimary).toContain("border-[color-mix");
    expect(styles.featureChip).toContain("bg-[var(--vui-control-muted)]");
    expect(styles.featureChip).toContain("[&_em]:rounded-full");
  });

  it("does not collapse VButton slot spans inside run mode chips", () => {
    expect(styles.featureChipRow).toContain("grid-cols-2");
    expect(styles.featureChip).toContain("!w-full");
    expect(styles.featureChip).toContain("[&_[data-slot=vui-button-content]]:min-w-0");
    expect(styles.featureChip).toContain("[&_[data-slot=vui-button-content]]:max-w-full");
    expect(styles.featureChip).toContain("[&_[data-slot=vui-button-label]]:min-w-0");
    expect(styles.featureChip).toContain("[&_[data-slot=vui-button-label]]:grid-cols-[minmax(0,1fr)_auto]");
    expect(styles.featureChip).toContain("[&_em]:shrink-0");
    expect(styles.featureChip).toContain("[&_strong]:truncate");
    expect(styles.featureChip).not.toContain("[&_strong]:whitespace-nowrap");
  });
});
