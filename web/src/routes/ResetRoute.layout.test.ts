import { describe, expect, it } from "vitest";

import routeSource from "./ResetRoute.tsx?raw";

describe("ResetRoute layout contract", () => {
  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("keeps reset inventory and guarded mutations on the reset API", () => {
    expect(routeSource).toContain("queryKeys.resetSummary()");
    expect(routeSource).toContain('fetchJson<ResetSummary>("/api/reset/summary")');
    expect(routeSource).toContain('fetchJson<ResetPreviewResponse>("/api/reset/preview"');
    expect(routeSource).toContain('fetchJson<ResetExecuteResponse>("/api/reset/execute"');
    expect(routeSource).toContain('method: "POST"');
  });

  it("reconciles Chat workspace state after destructive conversation reset", () => {
    expect(routeSource).toContain("CHAT_WORKSPACE_RESET_ITEM_IDS");
    expect(routeSource).toContain("resetResultAffectsChatWorkspace(payload)");
    expect(routeSource).toContain("useChatWorkbenchStore.getState().resetSessions()");
    expect(routeSource).toContain("chatWorkspaceCache.afterChatWorkspaceReset()");
  });

  it("renders cleanup empty and loading states as compact ledger rows", () => {
    expect(routeSource).toContain("function ResetLedgerEmptyState");
    expect(routeSource).toContain("styles.ledgerEmptyState");
    expect(routeSource).toContain("styles.ledgerEmptyRows");
    expect(routeSource).toContain("resetQuery.isLoading && !summary");
    expect(routeSource).not.toContain("<p className={styles.emptyState}>{copy.noPreview}</p>");
    expect(routeSource).not.toContain("<p className={styles.emptyState}>{copy.noResult}</p>");
  });
});
