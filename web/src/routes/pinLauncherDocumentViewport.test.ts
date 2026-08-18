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
      expect(node.style.width).toBe("945px");
      expect(node.style.maxWidth).toBe("945px");
      expect(node.style.minWidth).toBe("0");
    }
    expect(documentElement.style.getPropertyValue("--vui-window-width")).toBe("945px");
    restore();
    expect(documentElement.style.overflowX).toBe("");
  });
});
