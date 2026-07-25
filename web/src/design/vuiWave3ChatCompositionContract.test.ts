/**
 * Wave 3B composition contract — Chat session workbench is the domain demo path.
 *
 * Chat keeps its domain three-pane shell (not VListDetailPage). Composition means:
 * - layout root recipe marker
 * - region markers for index / center / status
 * - session index uses dense + selected + chrome recipes
 * - center/rail fills are opaque product surfaces
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { scanSourceForVuiSurfaceAlpha } from "./vuiSurfaceAlphaPolicy";
import chatStyles from "../routes/ChatCodingRoute.styles";
import sessionStyles from "../routes/DirectSessionIndexItem.styles";

const routesRoot = resolve(import.meta.dirname, "../routes");
const designRoot = resolve(import.meta.dirname);

describe("Wave 3B Chat session workbench composition", () => {
  it("marks the Chat layout root as the session workbench recipe", () => {
    const routeSource = readFileSync(resolve(routesRoot, "ChatCodingRoute.tsx"), "utf8");
    expect(routeSource).toContain('data-vui-recipe="chat-session-workbench"');
    expect(routeSource).toContain('data-vui-region="chat-conversation-center"');
    expect(routeSource).toContain("data-vui-layout-id");
    expect(routeSource).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(routeSource).toContain("PaneCollapseHandle");
  });

  it("keeps Chat width dual-write on shellStore (Wave 6D boundary)", () => {
    const layoutSource = readFileSync(resolve(routesRoot, "chat/useChatWorkbenchLayout.ts"), "utf8");
    expect(layoutSource).toContain("setChatPanelWidths");
    expect(layoutSource).toContain("attachAxisResizeSession");
    expect(layoutSource).toContain("getResizeBounds");
    // Coupled dual-pane math stays Chat-owned — do not import the generic width hook.
    expect(layoutSource).not.toMatch(/import\s*\{[^}]*usePersistedPaneResize/);
  });

  it("marks index and status rails as composition regions", () => {
    const indexSource = readFileSync(
      resolve(routesRoot, "chat/ChatConversationIndexRail.tsx"),
      "utf8",
    );
    const statusSource = readFileSync(resolve(routesRoot, "chat/ChatStatusRail.tsx"), "utf8");
    expect(indexSource).toContain('data-vui-region="chat-session-index"');
    expect(statusSource).toContain('data-vui-region="chat-status-rail"');
  });

  it("keeps session index structure on dense/selected/chrome recipes", () => {
    expect(sessionStyles.sessionItem).toMatch(/!bg-vui-surface-row|vuiDenseRowClass|!bg-\[var\(--vui-surface-row\)\]/);
    expect(sessionStyles.sessionItem).toContain("!bg-vui-surface-row");
    expect(sessionStyles.sessionItemActive).toContain(
      "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
    );
    expect(sessionStyles.sessionIconButton).toContain("h-[var(--vui-control-height-sm)]");
    expect(sessionStyles.sessionRunningBadge).toContain(
      "bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)]",
    );

    const hits = scanSourceForVuiSurfaceAlpha(
      `${sessionStyles.sessionItem} ${sessionStyles.sessionItemActive}`,
      "routes/DirectSessionIndexItem.styles.ts",
    );
    expect(hits.filter((h) => !h.allowed)).toEqual([]);
  });

  it("keeps chat center and rails on opaque product fills", () => {
    expect(chatStyles.centerSurface).toMatch(/!bg-vui-surface-chat|vuiChatFillClass/);
    expect(chatStyles.centerPane).toMatch(/!bg-vui-surface-chat|vuiChatFillClass/);
    expect(chatStyles.leftRail).toMatch(/!bg-vui-surface-rail|vuiRailFillClass/);
    expect(chatStyles.rightPane).toMatch(/!bg-vui-surface-rail|vuiRailFillClass/);
  });

  it("documents chrome + surface recipe modules as shared composition sources", () => {
    const chrome = readFileSync(resolve(designRoot, "vuiChromeRecipes.ts"), "utf8");
    const surfaces = readFileSync(resolve(designRoot, "vuiSurfaceRecipes.ts"), "utf8");
    expect(chrome).toContain("export const vuiControlIconSmClass");
    expect(chrome).toContain("export const vuiControlPillClass");
    expect(surfaces).toContain("export const vuiDenseRowClass");
    expect(surfaces).toContain("export const vuiStateSelectedRowClass");
    expect(surfaces).toContain("export const vuiChatFillClass");
  });
});
