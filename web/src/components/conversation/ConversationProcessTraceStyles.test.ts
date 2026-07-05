import { describe, expect, it } from "vitest";

import styles from "./ConversationView.styles";

describe("conversation process trace styles", () => {
  it("keeps timeline operation rows scannable instead of generated nested cards", () => {
    expect(styles.timelineCellHeader).toContain("grid-cols-[auto_auto_minmax(0,1fr)_auto_auto_auto]");
    expect(styles.timelineCellHeader).toContain("overflow-visible");
    expect(styles.timelineCellHeader).not.toContain("flex flex-wrap");
    expect(styles.timelineCellHeader).not.toContain("overflow-auto");

    expect(styles.timelineCellDetailButton).toContain("inline-grid");
    expect(styles.timelineCellDetailButton).toContain("size-6");
    expect(styles.timelineCellDetailButton).not.toMatch(/radius-panel|surface-glass|shadow-|overflow-auto|content-start/);

    expect(styles.timelineCommandRow).toContain("bg-transparent");
    expect(styles.timelineCommandRow).toContain("border-b");
    expect(styles.timelineCommandRow).not.toContain("overflow-auto");
    expect(styles.timelineCommandRow).not.toContain("bg-[var(--vui-surface-row)]");
  });

  it("keeps compact chat surface readable over the page background", () => {
    expect(styles.surfaceCompact).toContain("var(--vui-surface-panel)_72%");
    expect(styles.surfaceCompact).not.toContain("var(--surface-panel)");
    expect(styles.surfaceCompact).not.toContain("backdrop-blur");

    expect(styles.timelineCellPreview).toContain("line-clamp-1");
    expect(styles.timelineCellPreview).toContain("text-[var(--fg-secondary)]");
    expect(styles.timelineCellPreview).not.toContain("text-[var(--fg-tertiary)]");
  });
});
