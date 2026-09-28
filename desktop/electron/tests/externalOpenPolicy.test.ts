import { describe, expect, it } from "vitest";

import { isExternalOpenableUrl, normalizeAbsoluteOpenPath } from "../src/security/externalOpenPolicy.js";

describe("external open URL policy", () => {
  it("allows http, https and mailto", () => {
    expect(isExternalOpenableUrl("http://example.com/docs")).toBe(true);
    expect(isExternalOpenableUrl("https://example.com/docs?a=1#b")).toBe(true);
    expect(isExternalOpenableUrl("mailto:support@example.com")).toBe(true);
  });

  it("rejects non-whitelisted schemes", () => {
    expect(isExternalOpenableUrl("file:///C:/Windows/System32/calc.exe")).toBe(false);
    expect(isExternalOpenableUrl("javascript:alert(1)")).toBe(false);
    expect(isExternalOpenableUrl("data:text/html,hello")).toBe(false);
    expect(isExternalOpenableUrl("vibelncher://settings")).toBe(false);
    expect(isExternalOpenableUrl("about:blank")).toBe(false);
  });

  it("rejects malformed and non-string input", () => {
    expect(isExternalOpenableUrl("not a url")).toBe(false);
    expect(isExternalOpenableUrl("")).toBe(false);
    expect(isExternalOpenableUrl("   ")).toBe(false);
    expect(isExternalOpenableUrl(null)).toBe(false);
    expect(isExternalOpenableUrl(undefined)).toBe(false);
    expect(isExternalOpenableUrl(42)).toBe(false);
  });
});

describe("absolute open path policy", () => {
  it("accepts Windows drive, Windows UNC and POSIX absolute paths", () => {
    expect(normalizeAbsoluteOpenPath("C:\\docs\\a.pdf")).toBe("C:\\docs\\a.pdf");
    expect(normalizeAbsoluteOpenPath("c:/docs/a.pdf")).toBe("c:/docs/a.pdf");
    expect(normalizeAbsoluteOpenPath("\\\\server\\share\\a.pdf")).toBe("\\\\server\\share\\a.pdf");
    expect(normalizeAbsoluteOpenPath("/home/user/report.pdf")).toBe("/home/user/report.pdf");
    expect(normalizeAbsoluteOpenPath("  C:\\docs\\a.pdf  ")).toBe("C:\\docs\\a.pdf");
  });

  it("rejects relative paths and non-string input", () => {
    expect(normalizeAbsoluteOpenPath("docs/a.pdf")).toBeNull();
    expect(normalizeAbsoluteOpenPath("./docs/a.pdf")).toBeNull();
    expect(normalizeAbsoluteOpenPath("a.pdf")).toBeNull();
    expect(normalizeAbsoluteOpenPath("")).toBeNull();
    expect(normalizeAbsoluteOpenPath("   ")).toBeNull();
    expect(normalizeAbsoluteOpenPath("C:docs\\a.pdf")).toBeNull();
    expect(normalizeAbsoluteOpenPath(null)).toBeNull();
    expect(normalizeAbsoluteOpenPath(42)).toBeNull();
  });
});
