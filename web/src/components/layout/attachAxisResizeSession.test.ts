import { describe, expect, it } from "vitest";

import source from "./attachAxisResizeSession.ts?raw";

describe("attachAxisResizeSession", () => {
  it("owns window pointer listeners and body cursor for axis drag sessions", () => {
    expect(source).toContain('cursor: AxisResizeCursor');
    expect(source).toContain("document.body.style.cursor");
    expect(source).toContain("document.body.style.userSelect");
    expect(source).toContain('addEventListener("pointermove"');
    expect(source).toContain('addEventListener("pointerup"');
    expect(source).toContain('addEventListener("pointercancel"');
    expect(source).toContain("removeEventListener");
  });
});
