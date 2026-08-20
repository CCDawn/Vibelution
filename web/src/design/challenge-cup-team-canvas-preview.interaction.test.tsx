/** @vitest-environment happy-dom */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { ChallengeCupTeamCanvasPreviewApp } from "./challenge-cup-team-canvas-preview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("challenge cup team canvas preview", () => {
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
          <ChallengeCupTeamCanvasPreviewApp />
        </VuiProvider>,
      );
    });
    return container;
  }

  it("keeps the product Tailwind utility entry in the overlay import chain", () => {
    const previewSource = readFileSync(
      resolve(import.meta.dirname, "challenge-cup-team-canvas-preview.tsx"),
      "utf8",
    );
    const tokenIndex = previewSource.indexOf('"./tokens.css"');
    const tailwindIndex = previewSource.indexOf('"./tailwind.css"');
    const providerThemeIndex = previewSource.indexOf('"./vui-provider-theme.css"');
    expect(tokenIndex).toBeGreaterThan(-1);
    expect(tailwindIndex).toBeGreaterThan(tokenIndex);
    expect(providerThemeIndex).toBeGreaterThan(tailwindIndex);
    expect(previewSource).not.toContain("WORKBENCH_LAYOUT_IDS");
    expect(previewSource).toContain("VCanvasWorkbenchPage");
    expect(previewSource).not.toContain("ResearchProcessWorkspace");
  });

  it("puts team switching in the proposed toolbar instead of the left rail", async () => {
    const host = await mountPreview();
    expect(host.querySelector('[data-testid="layout-proposed"]')).toBeTruthy();
    expect(host.querySelector('[aria-label="切换团队"]')).toBeTruthy();
    expect(host.querySelector('[data-testid="current-team-rail"]')).toBeNull();
    expect(host.querySelector('[data-testid="status-rail"]')?.textContent).toContain("下一步");
    expect(host.querySelector('[data-testid="status-rail"]')?.textContent).toContain("资料寻找");
    expect(host.querySelector('[data-testid="status-rail"]')?.textContent).not.toContain("AI 搜索范围团队");
  });

  it("shows node details in the inspector after selecting a canvas node", async () => {
    const host = await mountPreview();
    expect(host.querySelector('[data-testid="inspector"]')?.textContent).toContain("白望舒");
    const idle = host.querySelector('[data-testid="scene-idle"]') as HTMLButtonElement | null;
    expect(idle).toBeTruthy();
    await act(async () => {
      idle?.click();
    });
    expect(host.querySelector('[data-testid="inspector-empty"]')).toBeTruthy();
    const node = host.querySelector('[data-testid="canvas-node-node-finder"]') as HTMLButtonElement | null;
    expect(node).toBeTruthy();
    await act(async () => {
      node?.click();
    });
    expect(host.querySelector('[data-testid="inspector"]')?.textContent).toContain("白望舒");
    expect(host.querySelector('[data-testid="inspector"]')?.textContent).toContain("source_finder");
  });

  it("keeps the current layout as a team list plus a flow strip over the canvas", async () => {
    const host = await mountPreview();
    const current = host.querySelector('[data-testid="compare-current"]') as HTMLButtonElement | null;
    await act(async () => {
      current?.click();
    });
    expect(host.querySelector('[data-testid="layout-current"]')).toBeTruthy();
    expect(host.querySelector('[data-testid="current-team-rail"]')?.textContent).toContain("挑战杯ai科研团队");
    expect(host.querySelector('[data-testid="current-team-rail"]')?.textContent).toContain("AI 搜索范围团队");
    expect(host.querySelector('[aria-label="切换团队"]')).toBeNull();
    expect(host.querySelector('[data-testid="layout-current"]')?.textContent).toContain("检查器默认隐藏");
  });

  it("surfaces an unbound-node issue in the blocked scene", async () => {
    const host = await mountPreview();
    const blocked = host.querySelector('[data-testid="scene-blocked"]') as HTMLButtonElement | null;
    await act(async () => {
      blocked?.click();
    });
    expect(host.querySelector('[data-testid="inspector-issue"]')?.textContent).toContain("NODE_UNBOUND");
    expect(host.querySelector('[data-testid="canvas-node-node-graph"]')?.getAttribute("aria-pressed")).toBe("true");
  });
});
