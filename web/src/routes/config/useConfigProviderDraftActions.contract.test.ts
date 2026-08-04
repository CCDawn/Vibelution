import { describe, expect, it } from "vitest";

import routeSource from "../ConfigRoute.tsx?raw";
import actionsSource from "./useConfigProviderDraftActions.ts?raw";

describe("useConfigProviderDraftActions contract", () => {
  it("owns create/discover/pin/suggest/unpin provider draft writes", () => {
    expect(actionsSource).toContain("export function useConfigProviderDraftActions");
    expect(actionsSource).toContain("handleDiscoverProvider");
    expect(actionsSource).toContain("handleCreateProvider");
    expect(actionsSource).toContain("handlePinProviderModels");
    expect(actionsSource).toContain("handleSuggestProviderId");
    expect(actionsSource).toContain("handleUnpinProviderModel");
    expect(actionsSource).toContain("/api/config/draft/providers");
    expect(actionsSource).toContain("Do not adopt response.hash (draft)");
  });

  it("is wired from ConfigRoute without inline pin/discover loops", () => {
    expect(routeSource).toContain("useConfigProviderDraftActions(");
    expect(routeSource).not.toContain("正在固定模型…（");
    expect(routeSource).toContain("handlePinProviderModels");
    expect(routeSource).toContain("handleDiscoverProvider");
  });
});
