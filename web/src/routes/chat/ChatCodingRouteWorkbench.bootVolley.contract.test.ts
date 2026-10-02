import { describe, expect, it } from "vitest";

import workbenchSource from "./ChatCodingRouteWorkbench.tsx?raw";

describe("ChatCodingRouteWorkbench boot volley contract", () => {
  it("lazily enables the financial-assistants query behind the session context menu", () => {
    expect(workbenchSource).toContain(
      "useFinancialAssistants(Boolean(sessionContextMenu))",
    );
    // No unconditional mount-time fetch: that call put
    // GET /api/financial-assistants into every app-open boot volley.
    expect(workbenchSource).not.toContain("useFinancialAssistants()");
  });

  it("keeps financial-assistants consumption inside the session context menu only", () => {
    expect(workbenchSource).toContain("financialAssistants.data?.some((item) =>");
    expect(workbenchSource).toContain("financialAssistants.data?.find((item) =>");
  });
});
