import { describe, expect, it } from "vitest";

import styles from "./AppShell.module.css";
import shellSource from "./AppShell.tsx?raw";

describe("AppShell layout contract", () => {
  it("renders one compact status summary chip while keeping the detailed guide panel", () => {
    expect(shellSource).toContain("statusSummaryChip");
    expect(shellSource).toContain("statusGuidePanel");
    expect(shellSource).not.toContain("rightStatusCards.map((item) => (\n                <span key={item.id} className={styles.statusBadge}>");
  });

  it("keeps the global shell top bar compact", () => {
    expect(styles.statusSummaryChip).toBeTypeOf("string");
    expect(styles.statusSummaryCount).toBeTypeOf("string");
  });
});
