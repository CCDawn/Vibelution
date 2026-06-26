import { describe, expect, it } from "vitest";
import { parseVibelutionDeepLink } from "../src/protocol/deepLink.js";

describe("Vibelution deep links", () => {
  it("parses launcher focus links", () => {
    expect(parseVibelutionDeepLink("vibelution://launcher/focus")).toEqual({ kind: "focus_launcher" });
  });

  it("preserves Windows workspace paths", () => {
    expect(
      parseVibelutionDeepLink("vibelution://workbench/open?path=C%3A%5CUsers%5C17533%5CDesktop%5CVibelution")
    ).toEqual({ kind: "open_workbench", path: "C:\\Users\\17533\\Desktop\\Vibelution" });
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
