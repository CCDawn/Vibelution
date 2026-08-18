import { describe, expect, it } from "vitest";

import {
  pinLauncherDocumentViewport,
  resolveLauncherVisibleCssWidth,
} from "./pinLauncherDocumentViewport";

function styleBox() {
  const vars: Record<string, string> = {};
  return {
    overflowX: "",
    maxWidth: "",
    width: "",
    minWidth: "",
    setProperty(name: string, value: string) {
      vars[name] = value;
    },
    getPropertyValue(name: string) {
      return vars[name] ?? "";
    },
  };
}

describe("resolveLauncherVisibleCssWidth", () => {
  it("divides a DIP-sized 1180 reading by renderer devicePixelRatio", () => {
    expect(
      resolveLauncherVisibleCssWidth({
        clientWidth: 1180,
        devicePixelRatio: 1.25,
      }),
    ).toBe(944);
  });

  it("keeps an already-visible CSS reading", () => {
    expect(
      resolveLauncherVisibleCssWidth({
        clientWidth: 945,
        devicePixelRatio: 1.25,
      }),
    ).toBe(945);
  });

  it("does not divide when devicePixelRatio is 1", () => {
    expect(
      resolveLauncherVisibleCssWidth({
        clientWidth: 1180,
        devicePixelRatio: 1,
      }),
    ).toBe(1180);
  });
});

describe("pinLauncherDocumentViewport", () => {
  it("clips html, body, and #root to the viewport instead of content min-size", () => {
    const documentElement = { style: styleBox(), clientWidth: 945 };
    const body = { style: styleBox() };
    const root = { style: styleBox() };
    const restore = pinLauncherDocumentViewport({
      documentElement,
      body,
      getElementById: (id: string) => (id === "root" ? root : null),
    } as unknown as Document);
    for (const node of [documentElement, body, root]) {
      expect(node.style.overflowX).toBe("clip");
      expect(node.style.width).toBe("min(945px, 100svw)");
      expect(node.style.maxWidth).toBe("min(945px, 100svw)");
      expect(node.style.minWidth).toBe("0");
    }
    expect(documentElement.style.getPropertyValue("--vui-window-width")).toBe("945px");
    restore();
    expect(documentElement.style.overflowX).toBe("");
  });

  it("pins a DIP-sized clientWidth down by devicePixelRatio", () => {
    const documentElement = { style: styleBox(), clientWidth: 1180 };
    const body = { style: styleBox() };
    const root = { style: styleBox() };
    pinLauncherDocumentViewport({
      documentElement,
      body,
      defaultView: { devicePixelRatio: 1.25, innerWidth: 1180, visualViewport: { width: 1180 } },
      getElementById: (id: string) => (id === "root" ? root : null),
    } as unknown as Document);
    expect(documentElement.style.getPropertyValue("--vui-window-width")).toBe("944px");
    expect(documentElement.style.width).toBe("min(944px, 100svw)");
  });
});
