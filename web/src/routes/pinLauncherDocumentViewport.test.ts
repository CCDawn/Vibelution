import { describe, expect, it } from "vitest";

import { pinLauncherDocumentViewport } from "./pinLauncherDocumentViewport";

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

describe("pinLauncherDocumentViewport", () => {
  it("clips html, body, and #root to the window instead of a pixel cap", () => {
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
      expect(node.style.width).toBe("100%");
      expect(node.style.maxWidth).toBe("100%");
      expect(node.style.minWidth).toBe("0");
    }
    expect(documentElement.style.getPropertyValue("--vui-window-width")).toBe("100svw");
    restore();
    expect(documentElement.style.overflowX).toBe("");
  });

  it("does not shrink a DIP-sized 1180 reading by devicePixelRatio", () => {
    const documentElement = { style: styleBox(), clientWidth: 1180 };
    const body = { style: styleBox() };
    const root = { style: styleBox() };
    pinLauncherDocumentViewport({
      documentElement,
      body,
      defaultView: { devicePixelRatio: 1.25, innerWidth: 1180, visualViewport: { width: 1180 } },
      getElementById: (id: string) => (id === "root" ? root : null),
    } as unknown as Document);
    expect(documentElement.style.getPropertyValue("--vui-window-width")).toBe("100svw");
    expect(documentElement.style.width).toBe("100%");
    expect(documentElement.style.maxWidth).toBe("100%");
    expect(documentElement.style.getPropertyValue("--vui-window-width")).not.toBe("944px");
  });
});
