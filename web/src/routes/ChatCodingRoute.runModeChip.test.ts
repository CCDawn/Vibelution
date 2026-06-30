import { describe, expect, it } from "vitest";

import styles from "./ChatCodingRoute.styles";

describe("ChatCodingRoute run mode chip visual contract", () => {
  it("keeps persistent enabled state on the dot instead of filling the whole chip", () => {
    expect(styles.featureChipActive).toContain("border-[color-mix");
    expect(styles.featureChipActive).toContain("text-[var(--fg-primary)]");
    expect(styles.featureChipActive).not.toContain(" bg-[var(--accent-cool)]");
    expect(styles.featureChipPrimary).toContain("border-[color-mix");
    expect(styles.featureChip).toContain("before:content-['']");
    expect(styles.featureChip).toContain("before:w-1.5");
    expect(styles.featureChipActive).toContain("before:bg-[var(--accent-cool)]");
    expect(styles.featureChipPrimary).toContain("before:bg-[var(--accent-warm-2)]");
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
    expect(styles.featureChip).toContain("[&_strong]:whitespace-nowrap");
    expect(styles.featureChip).not.toContain("overflow-wrap:anywhere");
  });
});
