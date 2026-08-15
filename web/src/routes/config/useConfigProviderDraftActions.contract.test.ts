import { describe, expect, it } from "vitest";

import configApiSource from "../../api/config.ts?raw";
import routeSource from "../ConfigRoute.tsx?raw";
import actionsSource from "./useConfigProviderDraftActions.ts?raw";

describe("useConfigProviderDraftActions contract", () => {
  it("owns create/discover/pin/suggest/unpin/delete/credential/route provider draft writes", () => {
    expect(actionsSource).toContain("export function useConfigProviderDraftActions");
    expect(actionsSource).toContain("handleDiscoverProvider");
    expect(actionsSource).toContain("handleCreateProvider");
    expect(actionsSource).toContain("handlePinProviderModels");
    expect(actionsSource).toContain("handleSuggestProviderId");
    expect(actionsSource).toContain("handleUnpinProviderModel");
    expect(actionsSource).toContain("handleDeleteProvider");
    expect(actionsSource).toContain("handleUpdateProviderCredential");
    expect(actionsSource).toContain("handleUpdateProviderContextWindow");
    expect(actionsSource).toContain("handlePreviewProviderRoute");
    expect(actionsSource).toContain("handleApplyProviderRoutePreview");
    expect(actionsSource).toContain("addDraftProvider(");
    expect(actionsSource).toContain("discoverDraftProvider(");
    expect(actionsSource).toContain("pinDraftProviderModel(");
    expect(actionsSource).toContain("unpinDraftProviderModel(");
    expect(actionsSource).toContain("deleteDraftProvider(");
    expect(actionsSource).toContain("updateDraftProvider(");
    expect(actionsSource).toContain("suggestDraftProviderId(");
    expect(actionsSource).toContain("previewDraftProviderRoute(");
    expect(actionsSource).toContain("Do not adopt response.hash (draft)");
    expect(configApiSource).toContain("/api/config/draft/providers");
    expect(configApiSource).toContain("/route-preview");
  });

  it("is wired from ConfigRoute without inline pin/discover/credential loops", () => {
    expect(routeSource).toContain("useConfigProviderDraftActions(");
    expect(routeSource).not.toContain("正在固定模型…（");
    expect(routeSource).not.toContain("正在保存 API Key…");
    expect(routeSource).not.toContain("正在生成路由预览…");
    expect(routeSource).toContain("handlePinProviderModels");
    expect(routeSource).toContain("handleDiscoverProvider");
    expect(routeSource).toContain("handleDeleteProvider");
    expect(routeSource).toContain("handleBeginProviderRouteEdit");
    // Migration lives in its own hook family (useConfigMigrationActions);
    // the draft provider actions must not re-own the migration endpoints.
    expect(routeSource).toContain("handlePreviewMigration");
    expect(routeSource).not.toContain("/api/config/migration/llm-v2/preview");
  });
});
