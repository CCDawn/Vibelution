import { describe, expect, it } from "vitest";
import {
  findVibelutionDeepLinkArg,
  parsePublicVibelutionDeepLink,
  parseVibelutionDeepLink
} from "../src/protocol/deepLink.js";

describe("Vibelution deep links", () => {
  it("parses launcher focus links", () => {
    expect(parseVibelutionDeepLink("vibelution://launcher/focus")).toEqual({ kind: "focus_launcher" });
  });

  it("preserves Windows workspace paths", () => {
    expect(
      parseVibelutionDeepLink("vibelution://workbench/open?path=C%3A%5CUsers%5C17533%5CDesktop%5CVibelution")
    ).toEqual({ kind: "open_workbench", path: "C:\\Users\\17533\\Desktop\\Vibelution" });
  });

  it("accepts only launcher focus as a public deep link action", () => {
    expect(parsePublicVibelutionDeepLink("vibelution://launcher/focus")).toEqual({
      kind: "focus_launcher",
      rawUrl: "vibelution://launcher/focus"
    });
  });

  it("keeps Workbench deep links internal and rejects them from the public OS entry", () => {
    expect(() =>
      parsePublicVibelutionDeepLink(
        "vibelution://workbench/open?path=C%3A%5CUsers%5C17533%5CDesktop%5CVibelution"
      )
    ).toThrow("deep link route is not public: open_workbench");
  });

  it("extracts the vibelution URL from Electron argv without treating ordinary paths as links", () => {
    expect(
      findVibelutionDeepLinkArg([
        "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe",
        "--flag",
        "vibelution://launcher/focus"
      ])
    ).toBe("vibelution://launcher/focus");
    expect(findVibelutionDeepLinkArg(["--workspace", "C:/Users/17533/Desktop/Vibelution"])).toBeNull();
  });

  it("rejects unsupported protocols", () => {
    expect(() => parseVibelutionDeepLink("https://example.com")).toThrow("unsupported protocol");
  });

  it("rejects lifecycle intent links in version 1", () => {
    expect(() =>
      parseVibelutionDeepLink("vibelution://lifecycle/intent?action=restart_after_apply&idempotencyKey=x")
    ).toThrow("unsupported deep link route");
  });
});
