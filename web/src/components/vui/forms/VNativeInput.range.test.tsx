/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { VNativeInput } from "./VNativeInput";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe("VNativeInput capsule range", () => {
  it("retains native values, callbacks and form identity for uncontrolled ranges", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const onChange = vi.fn();
    try {
      await act(async () => root.render(
        <VNativeInput type="range" rangeVariant="capsule" rangeTickCount={4} name="effort" id="effort" aria-label="Effort" min={0} max={3} step={1} defaultValue={1} onChange={onChange} />,
      ));
      const input = host.querySelector<HTMLInputElement>('input[type="range"]')!;
      expect(input.name).toBe("effort");
      expect(input.id).toBe("effort");
      expect(input.value).toBe("1");
      const rail = input.parentElement!;
      expect(parseFloat(rail.style.getPropertyValue("--vui-range-progress"))).toBeCloseTo(100 / 3);
      await act(async () => {
        Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, "3");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      expect(onChange).toHaveBeenCalledTimes(1);
      expect(input.value).toBe("3");
      expect(rail.style.getPropertyValue("--vui-range-progress")).toBe("100%");
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  });

  it("does not change plain native inputs or emit range-only attributes", () => {
    const html = renderToStaticMarkup(<VNativeInput type="text" rangeVariant="capsule" rangeTickCount={4} defaultValue="draft" />);
    expect(html).toContain('type="text"');
    expect(html).toContain('value="draft"');
    expect(html).not.toContain("--vui-range-progress");
    expect(html).not.toContain("rangeVariant");
    expect(html).not.toContain("rangeTickCount");
  });
});
