import { describe, expect, it } from "vitest";

import routeSource from "./ResetRoute.tsx?raw";

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
    expect(routeSource).not.toContain("queryKeys.resetSummary()");
    expect(routeSource).not.toContain('"/api/reset/summary"');
    expect(routeSource).not.toContain('"/api/reset/preview"');
    expect(routeSource).not.toContain('"/api/reset/execute"');
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
