/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { LauncherLayoutPreviewApp } from "./launcher-layout-preview";
import previewSource from "./launcher-layout-preview.tsx?raw";
import stylesSource from "./launcher-layout-preview.styles.ts?raw";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("launcher layout preview", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  async function mountPreview() {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <VuiProvider>
          <LauncherLayoutPreviewApp />
        </VuiProvider>,
      );
    });
    return container;
  }

  async function selectTab(host: HTMLElement, label: string) {
    const tab = Array.from(host.querySelectorAll('[role="tab"]')).find((node) =>
      node.textContent?.includes(label),
    ) as HTMLElement;
    await act(async () => {
      tab?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0 }));
      tab?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
      tab?.click();
    });
  }

  it("keeps the preview mock-only and wired to the VUI boundary", () => {
    expect(previewSource).toContain("../components/vui");
    expect(previewSource).not.toContain("renderers/shadcn");
    expect(previewSource).not.toContain("@heroui/react");
    expect(previewSource).not.toContain("routes/Launcher");
    expect(previewSource).not.toContain("requestBranchInstanceLifecycle");
    expect(previewSource).toContain("Mock-only");
  });

  it("uses the established preview Tailwind entry so the preview subtree is scanned", () => {
    expect(previewSource).toContain("./vui-component-preview/preview.tailwind.css");
    expect(previewSource).not.toContain("./tailwind.css");
  });

  it("reuses the project-native responsive grid class for the main/rail split", () => {
    expect(stylesSource).toContain("grid-cols-1");
    expect(stylesSource).toContain("lg:grid-cols-[minmax(0,1fr)_minmax(250px,0.32fr)]");
    expect(stylesSource).not.toContain("lg:grid-cols-[minmax(0,1fr)_320px]");
  });

  it("switches scenarios and renders one empty state without a table header when globally empty", async () => {
    const host = await mountPreview();
    expect(host.querySelector('[data-vui="dense-table"]')).toBeTruthy();

    await act(async () => {
      host.querySelector<HTMLButtonElement>('[data-scenario="attention"]')?.click();
    });
    expect(host.querySelector('[data-vui="dense-table"]')).toBeTruthy();
    expect(host.textContent).toContain("retired/team-cleanup");

    await act(async () => {
      host.querySelector<HTMLButtonElement>('[data-scenario="empty"]')?.click();
    });
    expect(host.querySelector('[data-vui="empty-state"]')).toBeTruthy();
    expect(host.querySelector('[data-vui="dense-table"]')).toBeNull();
    expect(host.querySelector("table")).toBeNull();
    expect(host.textContent).toContain("刷新（mock）");
  });

  it("selects a status tab to narrow the single branch surface", async () => {
    const host = await mountPreview();
    await selectTab(host, "已停止");

    const table = host.querySelector('[data-vui="dense-table"]');
    expect(table).toBeTruthy();
    expect(host.textContent).toContain("legacy-checkout");
    expect(host.textContent).not.toContain("feature/evolution");
  });

  it("collapses startup settings to a summary by default and expands into mock fields", async () => {
    const host = await mountPreview();

    const toggle = host.querySelector<HTMLButtonElement>('[data-startup-toggle]');
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(host.querySelector('[data-startup-summary]')?.textContent).toContain("development");
    expect(host.querySelector('[data-startup-summary]')?.textContent).toContain("8000");
    expect(host.querySelector('[data-startup-summary]')?.textContent).toContain("5173");
    expect(host.querySelector('[data-startup-summary]')?.textContent).toContain("窗口化");
    expect(host.querySelector('[data-startup-summary]')?.textContent).toContain("1440×900");
    expect(host.querySelector('[data-startup-fields]')).toBeNull();

    await act(async () => {
      toggle?.click();
    });
    expect(host.querySelector('[data-startup-fields]')).toBeTruthy();
    expect(host.querySelector('[data-startup-summary]')).toBeNull();
    expect(host.querySelector('[data-startup-toggle]')?.getAttribute("aria-expanded")).toBe("true");

    await act(async () => {
      host.querySelector<HTMLButtonElement>('[data-startup-toggle]')?.click();
    });
    expect(host.querySelector('[data-startup-summary]')).toBeTruthy();
    expect(host.querySelector('[data-startup-toggle]')?.getAttribute("aria-expanded")).toBe("false");
  });
});
