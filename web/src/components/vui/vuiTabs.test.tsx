/** @vitest-environment happy-dom */

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VTabs } from "./index";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("VTabs panel lifetime", () => {
  let host: HTMLDivElement;
  let root: Root | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    host?.remove();
    root = undefined;
  });

  function render(keepPanelsMounted?: boolean) {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => root?.render(<VTabs keepPanelsMounted={keepPanelsMounted} defaultValue="a" items={[
      { id: "a", label: "A", content: <input aria-label="Draft A" /> },
      { id: "b", label: "B", content: <input aria-label="Draft B" /> },
    ]} />));
  }

  function select(label: string) {
    const tab = Array.from(host.querySelectorAll('[role="tab"]')).find((node) => node.textContent === label);
    act(() => tab?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })));
  }

  it("preserves the default behavior of unmounting inactive bodies", () => {
    render();
    expect(host.querySelector('input[aria-label="Draft A"]')).toBeTruthy();
    expect(host.querySelector('input[aria-label="Draft B"]')).toBeNull();
    select("B");
    expect(host.querySelector('input[aria-label="Draft A"]')).toBeNull();
    expect(host.querySelector('input[aria-label="Draft B"]')).toBeTruthy();
  });

  it("keeps draft state and ARIA panel relationships when panel lifetime is retained", () => {
    render(true);
    const input = host.querySelector<HTMLInputElement>('input[aria-label="Draft A"]')!;
    input.value = "unfinished";
    select("B");
    expect(host.querySelector('input[aria-label="Draft A"]')).toBe(input);
    const inactive = input.closest('[role="tabpanel"]')!;
    expect(inactive.getAttribute("data-state")).toBe("inactive");
    expect(inactive.className).toContain("data-[state=inactive]:hidden");
    for (const tab of host.querySelectorAll('[role="tab"]')) {
      const panel = document.getElementById(tab.getAttribute("aria-controls")!);
      expect(panel?.getAttribute("aria-labelledby")).toBe(tab.id);
    }
    select("A");
    expect(input.value).toBe("unfinished");
    expect(input.closest('[role="tabpanel"]')?.getAttribute("data-state")).toBe("active");
  });
});
