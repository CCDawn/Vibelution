import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main public deep-link consumption", () => {
  it("routes second-instance protocol URLs through the public deep-link handler", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("findVibelutionDeepLinkArg(argv)");
    expect(source).toContain('handlePublicDeepLinkUrl(rawUrl, "second_instance")');
    expect(source).toContain('handlePublicDeepLinkUrl(rawUrl, "open_url")');
    expect(source).toContain("parsePublicVibelutionDeepLink(rawUrl)");
    expect(source).not.toContain("parseVibelutionDeepLink(rawUrl)");
  });
});
