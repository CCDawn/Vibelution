import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const testDir = dirname(fileURLToPath(import.meta.url));
const mainSource = readFileSync(resolve(testDir, "../src/main.ts"), "utf8");

describe("operator restart interrupt intent", () => {
  it("promotes a CLI launch-request restart to operator-restart", () => {
    const anchor = mainSource.indexOf(
      'provenance === "operator" && executionOperation === "restart"'
    );
    expect(anchor).toBeGreaterThanOrEqual(0);

    const window = mainSource.slice(anchor, anchor + 700);
    expect(window).toContain('? "operator-restart"');
    expect(window).toContain("effectiveProvenance");
    expect(window).toContain("orchestrateLauncherLifecycle(executionOperation");
    // The upgrade leaves a forensic console.warn trail behind.
    expect(window).toContain("LAUNCH_REQUEST_PROVENANCE_UPGRADE");
  });

  it("keeps operator-restart as the proven interrupt signal", () => {
    expect(mainSource).toContain(
      'interruptActiveWork: provenance === "operator-restart"'
    );
  });

  it("never promotes a forwarded restart", () => {
    const anchor = mainSource.indexOf(
      'provenance === "operator" && executionOperation === "restart"'
    );
    const condition = mainSource.slice(anchor, anchor + 120);
    expect(condition).toContain('provenance === "operator"');
    expect(condition).not.toContain("forwarded");
  });
});
