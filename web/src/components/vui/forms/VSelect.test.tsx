// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { VSelect, type VSelectProps } from "./VSelect";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe("controlled VSelect availability", () => {
  it.each([null, "missing", "blocked"])("clears an unavailable selection %s without retaining the previous Radix value", async selectedKey => {
    const node = document.createElement("div"); document.body.appendChild(node);
    const root = createRoot(node), onSelectionChange = vi.fn();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const options = [{ id: "ready", label: "可执行模型" }, { id: "blocked", label: "不可用模型", disabled: true }];
    const render = (props: Partial<VSelectProps>) => act(async () => root.render(<VSelect aria-label="研究模型" name="model" placeholder="选择可执行模型" options={options} onSelectionChange={onSelectionChange} {...props} />));
    try {
      await render({ selectedKey: "ready" });
      expect(node.querySelector('[role="combobox"]')?.textContent).toContain("可执行模型");
      await render({ selectedKey });
      expect(node.querySelector('[role="combobox"]')?.hasAttribute("data-placeholder")).toBe(true);
      expect(node.querySelector('[role="combobox"]')?.textContent).toContain("选择可执行模型");
      expect(node.querySelector<HTMLInputElement>('input[name="model"]')?.value).toBe("");
      await render({ selectedKey: "ready" });
      expect(node.querySelector('[role="combobox"]')?.hasAttribute("data-placeholder")).toBe(false);
      expect(node.querySelector('[role="combobox"]')?.textContent).toContain("可执行模型");
      expect(onSelectionChange).not.toHaveBeenCalled();
      expect([...warn.mock.calls, ...error.mock.calls].flat().join(" ")).not.toContain("uncontrolled");
    } finally {
      await act(async () => root.unmount()); node.remove(); warn.mockRestore(); error.mockRestore();
    }
  });
});
