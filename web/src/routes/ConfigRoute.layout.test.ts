import { describe, expect, it } from "vitest";

import routeSource from "./ConfigRoute.tsx?raw";

describe("ConfigRoute layout contract", () => {
  it("uses a full workspace placeholder for initial loading and load failure states", () => {
    expect(routeSource).toContain("function ConfigWorkspacePlaceholder");
    expect(routeSource).toContain("<ConfigWorkspacePlaceholder title={copy.loading} />");
    expect(routeSource).toContain('tone="error"');
    expect(routeSource).toContain("styles.loadingShell");
    expect(routeSource).toContain("styles.loadingBoard");
    expect(routeSource).not.toContain("<section className={styles.loadingSurface}>");
  });

  it("keeps the config loading placeholder as a dense board with nav, metrics, and specs", () => {
    expect(routeSource).toContain("styles.loadingNavPanel");
    expect(routeSource).toContain("styles.loadingNavList");
    expect(routeSource).toContain("styles.loadingMetricGrid");
    expect(routeSource).toContain("styles.loadingSpecGrid");
  });
});
