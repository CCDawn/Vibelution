import { describe, expect, it } from "vitest";

import routeSource from "../ConfigRoute.tsx?raw";
import actionsSource from "./useConfigProviderQuickSetupActions.ts?raw";

describe("useConfigProviderQuickSetupActions contract", () => {
  it("owns quick-setup prepare/confirm orchestration", () => {
    expect(actionsSource).toContain("export function useConfigProviderQuickSetupActions");
    expect(actionsSource).toContain("handlePrepareProviderQuickSetup");
    expect(actionsSource).toContain("handleConfirmProviderQuickSetup");
    expect(actionsSource).toContain("recommendProviderModel");
    expect(actionsSource).toContain("handleApply(");
  });

  it("is wired from ConfigRoute without inline check_succeeded loops", () => {
    expect(routeSource).toContain("useConfigProviderQuickSetupActions(");
    expect(routeSource).not.toContain('type: "check_succeeded"');
    expect(routeSource).toContain("handlePrepareProviderQuickSetup");
    expect(routeSource).toContain("handleConfirmProviderQuickSetup");
  });
});
