import { describe, expect, it } from "vitest";

import { assertLocalHttpUrl, isLiveWorkbenchWindowUrl } from "../src/security/urlPolicy.js";

describe("isLiveWorkbenchWindowUrl", () => {
  it("matches the configured origin", () => {
    expect(isLiveWorkbenchWindowUrl("http://127.0.0.1:8002/chat", "http://127.0.0.1:8002")).toBe(true);
  });

  it("matches another loopback backend port so product-entry can adopt the live window", () => {
    expect(isLiveWorkbenchWindowUrl("http://127.0.0.1:8002/", "http://127.0.0.1:8000")).toBe(true);
    expect(isLiveWorkbenchWindowUrl("http://localhost:8002/teams", "http://127.0.0.1:8000/")).toBe(true);
  });

  it("does not treat the Vite dev server as a workbench window", () => {
    expect(isLiveWorkbenchWindowUrl("http://127.0.0.1:5173/", "http://127.0.0.1:8000")).toBe(false);
  });

  it("rejects non-local URLs", () => {
    expect(isLiveWorkbenchWindowUrl("https://example.com/", "http://127.0.0.1:8000")).toBe(false);
  });
});

describe("assertLocalHttpUrl", () => {
  it("still requires the exact origin when loading a URL", () => {
    expect(assertLocalHttpUrl("http://127.0.0.1:8002/", "http://127.0.0.1:8002")).toBe("http://127.0.0.1:8002/");
    expect(() => assertLocalHttpUrl("http://127.0.0.1:8002/", "http://127.0.0.1:8000")).toThrow(/unexpected origin/);
  });
});
