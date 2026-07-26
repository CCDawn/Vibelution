import { describe, expect, it } from "vitest";

import { loadAgentsWorkbenchCopy, prefetchAgentsWorkbenchCopy } from "./loadAgentsWorkbenchCopy";

describe("loadAgentsWorkbenchCopy", () => {
  it("loads structured workbench copy module", async () => {
    const mod = await loadAgentsWorkbenchCopy();
    expect(mod.agentsRouteCopy("zh").title).toBe("Agent 中心");
    expect(typeof prefetchAgentsWorkbenchCopy).toBe("function");
    prefetchAgentsWorkbenchCopy();
  });
});
