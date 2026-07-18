import { describe, expect, it } from "vitest";

import styles from "./ChatCodingRoute.styles";
import chatCodingRouteSource from "./ChatCodingRoute.tsx?raw";
import tokenCoreStatusPanelSource from "./chat/TokenCoreStatusPanel.tsx?raw";

describe("ChatCodingRoute left status panel layout contract", () => {
  it("uses one raised status rail with flat separator-based groups", () => {
    expect(styles.leftRail).toContain("rounded-none");
    expect(styles.leftRail).toContain("border-l");
    expect(styles.leftRail).toContain("bg-[var(--vui-surface-rail)]");
    expect(styles.leftRail).toContain("shadow-none");
    expect(styles.leftBlock).toContain("border-b");
    expect(styles.leftBlock).toContain("bg-transparent");
    expect(styles.leftBlock).toContain("shadow-none");
    expect(styles.leftBlock).not.toContain("rounded-[var(--radius-panel)]");
    expect(styles.leftBlock).not.toContain("!bg-[var(--vui-surface-rail)]");
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

  it("keeps critical copy visible and moves token detail to accessible tooltip triggers", () => {
    expect(styles.currentSessionLine).toContain("whitespace-normal");
    expect(styles.currentSessionLine).toContain("[overflow-wrap:anywhere]");
    expect(styles.activeSkillStatus).toContain("grid-cols-[minmax(0,1fr)]");
    expect(styles.activeSkillIdentity).toContain("[&_strong]:whitespace-normal");
    expect(styles.activeSkillMeta).toContain("[&_span]:whitespace-normal");
    expect(styles.tokenStatusMeta).toContain("sr-only");
    expect(styles.tokenStatusMeta).not.toContain("line-clamp");
    expect(tokenCoreStatusPanelSource).toContain("VTooltip");
    expect(tokenCoreStatusPanelSource).toContain("renderTrigger");
    expect(tokenCoreStatusPanelSource).toContain("aria-label={cacheDetailOpenLabel}");
    expect(tokenCoreStatusPanelSource).toContain('aria-label={`${metric.label} ${metric.value}. ${metric.meta}`}');
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

  it("keeps provider failure status compact and hides numeric operator identities", () => {
    expect(chatCodingRouteSource).toContain("const compactSessionStateLine = detail?.lastTurnError");
    expect(chatCodingRouteSource).toContain("detail.lastTurnError.httpStatus || detail.lastTurnError.reasonCode");
    expect(chatCodingRouteSource).toContain("resolveChatUserDisplayName(runtime?.userName)");
  });
});
