// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveConversationInternalRoutePath } from "./conversationMarkdownInternalRoute";

const ORIGIN = "http://127.0.0.1:8000";

function setOrigin(origin: string) {
  vi.spyOn(window, "location", "get").mockReturnValue({ origin } as Location);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("resolveConversationInternalRoutePath", () => {
  it("routes relative paths the router owns", () => {
    expect(resolveConversationInternalRoutePath("/chat?session=s1")).toBe("/chat?session=s1");
    expect(resolveConversationInternalRoutePath("/agents")).toBe("/agents");
    expect(resolveConversationInternalRoutePath("/memory/library")).toBe("/memory/library");
    expect(resolveConversationInternalRoutePath("/")).toBe("/");
  });

  it("keeps backend asset paths on the plain anchor", () => {
    // Downloads are not views: an SPA navigation would hit an unregistered route.
    expect(resolveConversationInternalRoutePath("/api/sessions/s1/artifacts/a.png")).toBe("");
    expect(resolveConversationInternalRoutePath("/api/health")).toBe("");
    expect(resolveConversationInternalRoutePath("/static/app.js")).toBe("");
  });

  it("routes same-origin absolute links and strips the origin", () => {
    setOrigin(ORIGIN);
    expect(resolveConversationInternalRoutePath(`${ORIGIN}/chat?session=s1#turn-2`)).toBe(
      "/chat?session=s1#turn-2",
    );
    expect(resolveConversationInternalRoutePath(`${ORIGIN}/api/health`)).toBe("");
  });

  it("refuses cross-origin, protocol-relative and non-http schemes", () => {
    setOrigin(ORIGIN);
    expect(resolveConversationInternalRoutePath("https://example.com/chat")).toBe("");
    expect(resolveConversationInternalRoutePath("//example.com/chat")).toBe("");
    expect(resolveConversationInternalRoutePath("mailto:a@b.c")).toBe("");
    expect(resolveConversationInternalRoutePath("javascript:alert(1)")).toBe("");
  });

  it("stays conservative when the runtime has no browser origin", () => {
    // vitest runs with an origin unless overridden; blank it to model SSR.
    setOrigin("");
    expect(resolveConversationInternalRoutePath(`${ORIGIN}/chat?session=s1`)).toBe("");
  });

  it("ignores empty and unparseable input", () => {
    expect(resolveConversationInternalRoutePath("")).toBe("");
    expect(resolveConversationInternalRoutePath("   ")).toBe("");
    expect(resolveConversationInternalRoutePath("not a url")).toBe("");
  });
});
