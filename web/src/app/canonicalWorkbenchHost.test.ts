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
  });

  it("redirects before the app starts when the managed workbench is opened through localhost", () => {
    const replace = vi.fn();
    const location = {
      href: "http://localhost:8000/config",
      replace,
    } as unknown as Location;

    expect(redirectToCanonicalWorkbenchHost(location)).toBe(true);
    expect(replace).toHaveBeenCalledWith("http://127.0.0.1:8000/config");
  });
});
