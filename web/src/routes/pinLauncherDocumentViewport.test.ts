import { describe, expect, it } from "vitest";

import { pinLauncherDocumentViewport } from "./pinLauncherDocumentViewport";

function styleBox() {
  return { overflowX: "", maxWidth: "", width: "", minWidth: "" };
}

describe("pinLauncherDocumentViewport", () => {
  it("clips html, body, and #root to the viewport instead of content min-size", () => {
    const documentElement = { style: styleBox() };
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
    restore();
    expect(documentElement.style.overflowX).toBe("");
  });
});
