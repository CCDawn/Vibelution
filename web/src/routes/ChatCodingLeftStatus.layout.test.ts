import { describe, expect, it } from "vitest";

import styles from "./ChatCodingRoute.styles";

describe("ChatCodingRoute left status panel layout contract", () => {
  it("uses a readable solid panel surface instead of letting the scene image dominate text", () => {
    expect(styles.leftBlock).toContain("!bg-[var(--vui-surface-rail)]");
    expect(styles.leftBlock).toContain("border-[color-mix(in_srgb,var(--vui-border-strong)_66%,transparent)]");
    expect(styles.leftBlock).not.toContain("var(--vui-surface-glass)_58%,transparent");
    expect(styles.leftBlock).not.toContain("var(--vui-surface-panel)");
    expect(styles.leftBlock).not.toContain("white)");
    expect(styles.leftBlock).not.toContain("backdrop-blur");
  });

  it("keeps card headers on stable title and badge columns", () => {
    expect(styles.sectionHeader).toContain("!grid");
    expect(styles.sectionHeader).toContain("grid-cols-[minmax(0,1fr)_max-content]");
    expect(styles.sectionHeader).toContain("items-start");
    expect(styles.sectionHeader).not.toContain("flex-wrap");
    expect(styles.sectionMetaLine).toContain("whitespace-normal");
    expect(styles.sectionMetaLine).toContain("[overflow-wrap:anywhere]");
    expect(styles.sectionMetaLine).not.toContain("truncate");
  });

  it("does not truncate critical current session, skill, token, or companion copy", () => {
    expect(styles.currentSessionLine).toContain("whitespace-normal");
    expect(styles.currentSessionLine).toContain("[overflow-wrap:anywhere]");
    expect(styles.activeSkillStatus).toContain("grid-cols-[minmax(0,1fr)]");
    expect(styles.activeSkillIdentity).toContain("[&_strong]:whitespace-normal");
    expect(styles.activeSkillMeta).toContain("[&_span]:whitespace-normal");
    expect(styles.tokenStatusMeta).toContain("whitespace-normal");
    expect(styles.tokenStatusMeta).toContain("[overflow-wrap:anywhere]");
    expect(styles.tokenStatusMeta).not.toContain("line-clamp");
    expect(styles.companionCopy).toContain("[&>p]:whitespace-normal");
    expect(styles.companionTopLine).toContain("[&_strong]:whitespace-normal");
    expect(styles.companionTopLine).toContain("[&_span]:whitespace-normal");
    expect(styles.companionBlock).toContain("overflow-visible");
    expect(styles.companionBlock).not.toContain("overflow-hidden");
    expect(styles.companionBlock).not.toContain("!flex-1");
    expect(styles.companionCopy).not.toContain("truncate");
    expect(styles.companionTopLine).not.toContain("truncate");
  });

  it("lets compact meta rows and action labels wrap without horizontal scrollbars", () => {
    expect(styles.inlineMetaList).toContain("overflow-visible");
    expect(styles.inlineMetaList).not.toContain("overflow-auto");
    expect(styles.inlineMetaPill).toContain("[&_span]:whitespace-normal");
    expect(styles.inlineMetaPill).toContain("[&_strong]:whitespace-normal");
    expect(styles.inlineStat).toContain("[&_strong]:whitespace-normal");
    expect(styles.featureChip).toContain("[&_strong]:whitespace-normal");
    expect(styles.petShowcaseAction).toContain("[&_span]:whitespace-normal");
    expect(styles.inlineMetaPill).not.toContain("[&_strong]:truncate");
    expect(styles.petShowcaseAction).not.toContain("[&_span]:truncate");
  });
});
