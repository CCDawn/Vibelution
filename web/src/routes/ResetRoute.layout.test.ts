import { describe, expect, it } from "vitest";

import routeSource from "./ResetRoute.tsx?raw";
import styles from "./ResetRoute.styles";

function hasRealBackgroundToken(className: string) {
  return className
    .split(/\s+/)
    .some((token) => token.startsWith("bg-[") || token.startsWith("[background:"));
}

function expectBackgroundAware(className: string) {
  expect(hasRealBackgroundToken(className)).toBe(true);
  const backgroundTokens = className
    .split(/\s+/)
    .filter((token) => token.startsWith("bg-[") || token.startsWith("[background:"));
  expect(backgroundTokens.some((token) => token.includes("color-mix(in_srgb") && token.includes("transparent"))).toBe(true);
}

function classTokens(className: string) {
  return className.split(/\s+/).filter(Boolean);
}

function styleValue(key: string) {
  return (styles as Record<string, string>)[key] ?? "";
}

describe("ResetRoute layout contract", () => {
  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("retires the Web Reset surface in favor of Launcher maintenance", () => {
    expect(routeSource).toContain("Launcher 维护中心");
    expect(routeSource).toContain('href="/launcher"');
    expect(routeSource).toContain('data-reset-retired="launcher-owned"');
    expect(routeSource).toContain('data-reset-status="retired"');
    expect(routeSource).toContain('data-reset-action="launcher-maintenance"');
    expect(routeSource).toContain('data-reset-risk="web-api-retired"');
    expect(routeSource).not.toContain("queryKeys.resetSummary()");
    expect(routeSource).not.toContain('"/api/reset/summary"');
    expect(routeSource).not.toContain('"/api/reset/preview"');
    expect(routeSource).not.toContain('"/api/reset/execute"');
  });

  it("keeps the retired route root background-aware", () => {
    expect(styles.routeClass).not.toContain("bg-[var(--surface-page)]");
    expect(styles.routeClass).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.routeClass).toContain("min-w-0");
    expect(styles.routeClass).toContain("max-w-full");
    expect(styles.routeClass).toContain("overflow-x-hidden");
    expectBackgroundAware(styles.headerClass);
    expect(styles.headerClass).not.toContain("shadow-[var(--vui-shadow-hairline)]");
  });

  it("keeps retired Reset panels light and background-aware", () => {
    expectBackgroundAware(styles.cardClass);
    expect(styles.cardClass).not.toContain("bg-[var(--surface-panel)]");
    expect(styles.cardClass).not.toContain("bg-[var(--surface-card)]");
    expect(styles.cardClass).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(styles.workspaceClass).toContain("min-w-0");
    expect(styles.workspaceClass).toContain("max-w-full");
    expect(styles.workspaceClass).toContain("overflow-x-hidden");
    expect(styles.cardClass).toContain("min-w-0");
  });

  it("lays out the retired state, action entry, and risk notes as a compact workbench", () => {
    expect(styleValue("workspaceClass")).toContain("grid-cols-[minmax(0,1.2fr)_clamp(260px,28vw,420px)]");
    expect(styleValue("primaryColumnClass")).toContain("max-w-none");
    expect(styleValue("workspaceClass")).toContain("items-start");
    expect(styleValue("workspaceClass")).toContain("justify-start");
    expect(styleValue("workspaceClass")).toContain("overflow-y-auto");
    expect(styleValue("workspaceClass")).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");

    expect(styleValue("statusStripClass")).toContain("grid-cols-[auto_minmax(0,1fr)]");
    expect(styleValue("statusStripClass")).toContain("max-w-none");
    expect(styleValue("statusStripClass")).toContain("overflow-hidden");
    expectBackgroundAware(styleValue("statusStripClass"));

    expect(styleValue("launcherPanelClass")).toContain("max-w-none");
    expect(styleValue("launcherPanelClass")).toContain("content-start");
    expectBackgroundAware(styleValue("launcherPanelClass"));

    expect(styleValue("riskPanelClass")).toContain("max-w-none");
    expect(styleValue("riskPanelClass")).toContain("content-start");
    expect(styleValue("riskListClass")).toContain("max-h-[220px]");
    expect(styleValue("riskListClass")).toContain("overflow-auto");
    expect(styleValue("riskItemClass")).toContain("grid-cols-[auto_minmax(0,1fr)]");
  });

  it("lets retired-page copy wrap instead of hiding important migration details", () => {
    expect(styleValue("copyTextClass")).toContain("break-words");
    expect(styleValue("copyTextClass")).toContain("[overflow-wrap:anywhere]");
    expect(styleValue("copyTextClass")).not.toContain("truncate");
    expect(styleValue("subtitleClass")).not.toContain("truncate");
  });

  it("keeps the Launcher action content-sized outside mobile full-width contexts", () => {
    expect(styles.headerActionsClass).toContain("flex-wrap");
    expect(styles.secondaryButtonClass).toContain("w-fit");
    expect(styles.secondaryButtonClass).toContain("max-w-full");
    expect(classTokens(styles.secondaryButtonClass)).not.toContain("w-full");
  });

  it("keeps destructive reset execution out of the Web workbench", () => {
    expect(routeSource).not.toContain("CHAT_WORKSPACE_RESET_ITEM_IDS");
    expect(routeSource).not.toContain("resetResultAffectsChatWorkspace(payload)");
    expect(routeSource).not.toContain("useChatWorkbenchStore.getState().resetSessions()");
    expect(routeSource).not.toContain("chatWorkspaceCache.afterChatWorkspaceReset()");
    expect(routeSource).not.toContain("useMutation");
  });

  it("does not preserve the old cleanup ledger implementation", () => {
    expect(routeSource).not.toContain("function ResetLedgerEmptyState");
    expect(routeSource).not.toContain("styles.ledgerEmptyState");
    expect(routeSource).not.toContain("styles.ledgerEmptyRows");
    expect(routeSource).not.toContain("resetQuery.isLoading && !summary");
  });
});
