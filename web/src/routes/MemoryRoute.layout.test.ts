import { describe, expect, it } from "vitest";

import routeSource from "./MemoryRoute.tsx?raw";
import routerSource from "../app/router.tsx?raw";
import appShellSource from "../app/AppShell.tsx?raw";

describe("MemoryRoute layout contract", () => {
  it("reads the read-only memory overview endpoint through the shared query key", () => {
    expect(routeSource).toContain("queryKeys.memoryOverview()");
    expect(routeSource).toContain('fetchJson<MemoryOverview>("/api/memory/overview")');
  });

  it("keeps source, item, and detail panels as the primary page structure", () => {
    const sourcePanelIndex = routeSource.indexOf("styles.sourcePanel");
    const itemPanelIndex = routeSource.indexOf("styles.itemPanel");
    const detailPanelIndex = routeSource.indexOf("styles.detailPanel");

    expect(sourcePanelIndex).toBeGreaterThan(0);
    expect(itemPanelIndex).toBeGreaterThan(sourcePanelIndex);
    expect(detailPanelIndex).toBeGreaterThan(itemPanelIndex);
  });

  it("surfaces agent visibility, prompt injection, and raw content in the detail pane", () => {
    expect(routeSource).toContain("activeItem.agentVisible");
    expect(routeSource).toContain("activeItem.inPrompt");
    expect(routeSource).toContain("<details className={styles.rawPanel} open>");
    expect(routeSource).toContain("activeItem.content");
  });

  it("is registered as an independent top-level route and global nav item", () => {
    expect(routerSource).toContain('path: "memory"');
    expect(routerSource).toContain("<MemoryRoute />");
    expect(appShellSource).toContain('to="/memory"');
    expect(appShellSource).toContain('t("navMemory")');
  });
});
