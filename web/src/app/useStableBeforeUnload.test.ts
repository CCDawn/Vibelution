import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "useStableBeforeUnload.ts"), "utf8");

describe("useStableBeforeUnload", () => {
  it("keeps a single stable beforeunload binding via ref + empty-ish effect deps", () => {
    expect(source).toContain("handlerRef.current = handler");
    expect(source).toContain('window.addEventListener("beforeunload", onBeforeUnload)');
    expect(source).toContain("return () => window.removeEventListener(\"beforeunload\", onBeforeUnload)");
    // Only skipElectronDesktopShell may re-run the effect — not polled status.
    expect(source).toMatch(/\}, \[skipElectronDesktopShell\]\);/);
    expect(source).not.toMatch(/addEventListener\("beforeunload"[\s\S]*?\}, \[[^\]]*status/);
  });
});
