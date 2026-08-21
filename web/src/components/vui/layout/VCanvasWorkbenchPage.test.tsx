/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VCanvasWorkbenchPage } from "./VCanvasWorkbenchPage";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
let root: Root | null = null;

function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    value: width,
  });
  act(() => window.dispatchEvent(new Event("resize")));
}

function pageElement(responsive = false, title = "Research canvas") {
  return (
    <VCanvasWorkbenchPage
      ariaLabel="Research canvas"
      canvas={<div data-testid="canvas">Canvas</div>}
      hideHeader
      inspector={<button type="button">Inspector action</button>}
      rail={<button type="button">Rail action</button>}
      responsive={
        responsive
          ? {
              enabled: true,
              rail: { label: "阶段栏" },
              inspector: { label: "检查器" },
            }
          : undefined
      }
      title={title}
    />
  );
}

function renderPage(width: number, responsive = false) {
  setViewport(width);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(pageElement(responsive));
  });
  return host;
}

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(
    container.querySelectorAll<HTMLButtonElement>("button"),
  ).find((candidate) => candidate.textContent?.includes(text));
  if (!button) throw new Error(`button not found: ${text}`);
  return button;
}

afterEach(() => {
  if (root) act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
  document.body.style.overflow = "";
});

describe("VCanvasWorkbenchPage responsive contract", () => {
  it("keeps the existing fixed three-slot recipe when the API is omitted", () => {
    const container = renderPage(960);

    expect(
      container.querySelector(
        '[data-vui="canvas-workbench-responsive-controls"]',
      ),
    ).toBeNull();
    expect(
      container.querySelector('[data-vui="split-sidebar"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-vui="split-aside"]')).not.toBeNull();
  });

  it("keeps rail and Inspector columns at the wide breakpoint", () => {
    const container = renderPage(1280, true);

    expect(
      container.querySelector(
        '[data-vui="canvas-workbench-responsive-controls"]',
      ),
    ).toBeNull();
    expect(
      container.querySelector('[data-vui="split-sidebar"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-vui="split-aside"]')).not.toBeNull();
  });

  it("turns only Inspector into a modal drawer in compact desktop", async () => {
    const container = renderPage(1000, true);
    const controls = container.querySelector(
      '[data-vui="canvas-workbench-responsive-controls"]',
    );
    expect(controls?.textContent).toContain("打开检查器");
    expect(controls?.textContent).not.toContain("阶段栏");
    expect(
      container.querySelector('[data-vui="split-sidebar"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-vui="split-aside"]')).toBeNull();

    const toggle = buttonByText(container, "打开检查器");
    act(() => toggle.click());

    const drawer = document.body.querySelector<HTMLElement>(
      '[data-vui-region="canvas-workbench-drawer"]',
    );
    const dialog = drawer?.closest<HTMLElement>('[data-vui="dialog-content"]');
    expect(dialog?.getAttribute("role")).toBe("dialog");
    expect(dialog?.querySelector('[data-slot="dialog-title"]')?.textContent).toBe("检查器");
    expect(dialog?.className).toContain("!translate-x-0");
    expect(dialog?.className).toContain("!translate-y-0");
    expect(document.body.querySelector('[data-vui="dialog-overlay"]')).not.toBeNull();

    const close = dialog?.querySelector<HTMLButtonElement>('[data-vui="dialog-close"]');
    const inner = drawer?.querySelector<HTMLButtonElement>(
      "button",
    );
    expect(close).not.toBeNull();
    expect(inner).not.toBeNull();
    inner?.focus();
    act(() => {
      root?.render(pageElement(true, "Research canvas updated"));
    });
    expect(document.activeElement).toBe(inner);

    await act(async () => {
      drawer?.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Escape",
          bubbles: true,
          cancelable: true,
        }),
      );
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    });
    expect(
      document.body.querySelector('[data-vui-region="canvas-workbench-drawer"]'),
    ).toBeNull();
    expect(document.activeElement).toBe(toggle);
  });

  it("turns both side slots into independently toggled drawers below 900px", () => {
    const container = renderPage(800, true);

    expect(container.querySelector('[data-vui="split-sidebar"]')).toBeNull();
    expect(container.querySelector('[data-vui="split-aside"]')).toBeNull();
    expect(
      container.querySelector(
        '[data-vui="canvas-workbench-responsive-controls"]',
      )?.textContent,
    ).toContain("打开阶段栏");
    expect(
      container.querySelector(
        '[data-vui="canvas-workbench-responsive-controls"]',
      )?.textContent,
    ).toContain("打开检查器");

    const railToggle = buttonByText(container, "打开阶段栏");
    act(() => railToggle.click());
    expect(
      document.body.querySelector('[data-vui-region="canvas-workbench-drawer"]')
        ?.closest('[data-vui="dialog-content"]')
        ?.querySelector('[data-slot="dialog-title"]')
        ?.textContent,
    ).toBe("阶段栏");
    act(() =>
      document.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Escape",
          bubbles: true,
          cancelable: true,
        }),
      ),
    );
    expect(
      document.body.querySelector('[data-vui-region="canvas-workbench-drawer"]'),
    ).toBeNull();

    const inspectorToggle = buttonByText(container, "打开检查器");
    act(() => inspectorToggle.click());
    expect(
      document.body.querySelector('[data-vui-region="canvas-workbench-drawer"]')
        ?.closest('[data-vui="dialog-content"]')
        ?.querySelector('[data-slot="dialog-title"]')
        ?.textContent,
    ).toBe("检查器");
  });
});
