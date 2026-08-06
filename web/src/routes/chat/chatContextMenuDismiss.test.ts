import { describe, expect, it } from "vitest";

import { eventInsideContextMenuSurface } from "./chatContextMenuDismiss";

function elementWithClosest(match: string | null): Element {
  return {
    closest(selector: string) {
      if (match == null) {
        return null;
      }
      if (selector === match || selector.includes(match.replace(/[[\]"=]/g, ""))) {
        return this as unknown as Element;
      }
      // Support exact attribute selectors used in production.
      if (match === "dropdown-menu" && selector === '[data-vui="dropdown-menu"]') {
        return this as unknown as Element;
      }
      if (match === "agent-context" && selector === "[data-agent-context-menu]") {
        return this as unknown as Element;
      }
      if (match === "radix-content" && selector === "[data-radix-dropdown-menu-content]") {
        return this as unknown as Element;
      }
      return null;
    },
  } as Element;
}

describe("eventInsideContextMenuSurface", () => {
  it("returns false for null / non-elements", () => {
    expect(eventInsideContextMenuSurface(null)).toBe(false);
    expect(eventInsideContextMenuSurface({} as EventTarget)).toBe(false);
  });

  it("detects portaled dropdown menu surfaces", () => {
    expect(eventInsideContextMenuSurface(elementWithClosest("dropdown-menu"))).toBe(true);
  });

  it("detects agent context menu markers", () => {
    expect(eventInsideContextMenuSurface(elementWithClosest("agent-context"))).toBe(true);
  });

  it("detects radix content wrappers", () => {
    expect(eventInsideContextMenuSurface(elementWithClosest("radix-content"))).toBe(true);
  });

  it("returns false outside menu surfaces", () => {
    expect(eventInsideContextMenuSurface(elementWithClosest(null))).toBe(false);
  });
});
