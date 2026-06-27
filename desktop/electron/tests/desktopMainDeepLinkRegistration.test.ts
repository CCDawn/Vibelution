import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main deep-link startup registration", () => {
  it("uses the shared deep-link registration helper before bootstrapping Launcher", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const registrationIndex = source.indexOf("registerPackagedDeepLinks(paths)");
    const bootstrapIndex = source.indexOf("launcherBootstrap = await bootstrapLauncherIfEnabled(paths)");

    expect(source).toContain("registerPackagedDeepLinks(paths)");
    expect(source).toContain("registerDeepLinkProtocolIfAllowed");
    expect(source).toContain("smoke: desktopCliArgs.smoke");
    expect(registrationIndex).toBeGreaterThan(-1);
    expect(bootstrapIndex).toBeGreaterThan(-1);
    expect(registrationIndex).toBeLessThan(bootstrapIndex);
  });
});
