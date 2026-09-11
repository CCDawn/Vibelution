import { describe, expect, it } from "vitest";

import routeStyles from "./ChatCodingRoute.styles";
import conversationIndexRailStyles from "./chat/ChatConversationIndexRail.styles";
import tokenCoreStyles from "./chat/TokenCoreStatusPanel.styles";

const styles = {
  ...routeStyles,
  ...conversationIndexRailStyles,
  ...tokenCoreStyles,
} as Record<string, string>;
import chatCodingRouteSource from "./chat/ChatCodingRouteWorkbench.tsx?raw";
import chatSessionSurfaceModelSource from "./chat/chatSessionSurfaceModel.ts?raw";
import tokenCoreStatusPanelSource from "./chat/TokenCoreStatusPanel.tsx?raw";

const routeAndSessionSurfaceSource = `${chatCodingRouteSource}\n${chatSessionSurfaceModelSource}`;

describe("ChatCodingRoute left status panel layout contract", () => {
  it("uses one raised status rail with flat separator-based groups", () => {
    expect(styles.leftRail).toContain("rounded-none");
    expect(styles.leftRail).toContain("border-l");
    expect(styles.leftRail).toMatch(/bg-vui-surface-rail|bg-\[var\(--vui-surface-rail\)\]/);
    expect(styles.leftRail).toContain("shadow-none");
    // Whitespace rhythm replaces hairline separators between rail sections.
    expect(styles.leftBlock).not.toContain("border-b");
    expect(styles.leftBlock).toContain("border-0");
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
    // Chat status rail retired: the current-session line and active-skill chip
    // styles went with it; token detail stays behind tooltip triggers.
    expect(styles.tokenStatusMeta).toContain("sr-only");
    expect(styles.tokenStatusMeta).not.toContain("line-clamp");
    expect(tokenCoreStatusPanelSource).toContain("VTooltip");
    expect(tokenCoreStatusPanelSource).toContain("renderTrigger");
    expect(tokenCoreStatusPanelSource).toContain("aria-label={cacheDetailOpenLabel}");
    expect(tokenCoreStatusPanelSource).toContain('aria-label={`${metric.label} ${metric.value}. ${metric.meta}`}');
  });

  it("keeps provider failure status compact and hides numeric operator identities", () => {
    expect(routeAndSessionSurfaceSource).toContain("const compactSessionStateLine = detail?.lastTurnError");
    expect(routeAndSessionSurfaceSource).toContain("detail.lastTurnError.httpStatus || detail.lastTurnError.reasonCode");
    expect(chatCodingRouteSource).toContain("resolveChatUserDisplayName(runtime?.userName)");
  });
});
