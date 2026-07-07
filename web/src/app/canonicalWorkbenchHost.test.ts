import { describe, expect, it, vi } from "vitest";

import { canonicalWorkbenchHref, redirectToCanonicalWorkbenchHost } from "./canonicalWorkbenchHost";

describe("canonical workbench host", () => {
  it("rewrites the managed workbench localhost origin to 127.0.0.1", () => {
    expect(canonicalWorkbenchHref("http://localhost:8000/self-evolution?track=self#now")).toBe(
      "http://127.0.0.1:8000/self-evolution?track=self#now",
    );
  });

  it("leaves dev and non-workbench origins alone", () => {
    expect(canonicalWorkbenchHref("http://localhost:5173/self-evolution")).toBe("");
    expect(canonicalWorkbenchHref("http://127.0.0.1:8000/self-evolution")).toBe("");
    expect(canonicalWorkbenchHref("https://localhost:8000/self-evolution")).toBe("");
    expect(canonicalWorkbenchHref("http://127.0.0.1:8765/launcher")).toBe("");
  });

  it("redirects before the app starts when the managed workbench is opened through localhost", () => {
    const replace = vi.fn();
    const location = {
      href: "http://localhost:8000/config",
      replace,
    } as unknown as Location;
    const metaElements: Array<{ setAttribute: ReturnType<typeof vi.fn>; parentElement: unknown }> = [];
    const targetDocument = {
      head: {
        appendChild: vi.fn((element) => {
          element.parentElement = targetDocument.head;
        }),
      },
      querySelector: vi.fn(() => null),
      createElement: vi.fn(() => {
        const element = { setAttribute: vi.fn(), parentElement: null };
        metaElements.push(element);
        return element;
      }),
    } as unknown as Document;

    expect(redirectToCanonicalWorkbenchHost(location, targetDocument)).toBe(true);
    expect(replace).toHaveBeenCalledWith("http://127.0.0.1:8000/config");
    expect(metaElements[0]?.setAttribute).toHaveBeenCalledWith("content", "no-referrer");
  });

  it("redirects workbench routes away from the launcher control port", () => {
    expect(canonicalWorkbenchHref("http://127.0.0.1:8765/self-evolution")).toBe(
      "http://127.0.0.1:8000/self-evolution",
    );
    expect(canonicalWorkbenchHref("http://localhost:8765/memory/graph?tab=1")).toBe(
      "http://127.0.0.1:8000/memory/graph?tab=1",
    );
  });
});
