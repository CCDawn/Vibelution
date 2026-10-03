/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ToolRegistryItem } from "../api/types";
import { ToolPermissionGroupDisclosure, ToolRegistryVirtualList, type ToolRegistryVirtualRow } from "./ToolsRoute";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
let root: Root | null = null;
let permissionChildrenRenderCount = 0;
let originalGetBoundingClientRect: typeof HTMLElement.prototype.getBoundingClientRect | null = null;
let originalElementScrollTo: typeof HTMLElement.prototype.scrollTo | null = null;
let originalDimensionDescriptors: Map<string, PropertyDescriptor | undefined> | null = null;
let maxRequestedScrollTop = 0;
let elementScrollCallCount = 0;

function DisclosureHarness({ forceOpen = false, label = "Package A" }: { forceOpen?: boolean; label?: string }) {
  return (
    <ToolPermissionGroupDisclosure
      className="permission-group"
      summaryClassName="permission-summary"
      listClassName="permission-rows"
      summary={<span>{label}</span>}
      forceOpen={forceOpen}
      renderChildren={() => {
        permissionChildrenRenderCount += 1;
        return <article data-testid="permission-row">Per-tool permission controls</article>;
      }}
    />
  );
}

function renderDisclosure(props?: { forceOpen?: boolean; label?: string }) {
  permissionChildrenRenderCount = 0;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(<DisclosureHarness {...props} />);
  });
  return host;
}

function stubRegistryViewport() {
  maxRequestedScrollTop = 0;
  elementScrollCallCount = 0;
  originalDimensionDescriptors = new Map<string, PropertyDescriptor | undefined>(
    ["offsetWidth", "offsetHeight", "clientHeight", "scrollHeight"].map((property) => [
      property,
      Object.getOwnPropertyDescriptor(HTMLElement.prototype, property),
    ]),
  );
  originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function () {
    const index = this.getAttribute("data-index");
    const height = index === null ? 440 : 62;
    return {
      width: 380,
      height,
      top: 0,
      left: 0,
      bottom: height,
      right: 380,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect;
  };
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get: () => 380,
  });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      return this.getAttribute("data-index") === null ? 440 : 62;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get() {
      return this.classList.contains("tool-list") ? 440 : 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "scrollHeight", {
    configurable: true,
    get() {
      if (!this.classList.contains("tool-list")) return 0;
      return Number.parseFloat((this.firstElementChild as HTMLElement | null)?.style.height ?? "") || 440;
    },
  });
  originalElementScrollTo = HTMLElement.prototype.scrollTo;
  HTMLElement.prototype.scrollTo = function (optionsOrX, y) {
    elementScrollCallCount += 1;
    const top = typeof optionsOrX === "number" ? y ?? 0 : optionsOrX.top ?? this.scrollTop;
    maxRequestedScrollTop = Math.max(maxRequestedScrollTop, top);
    this.scrollTop = top;
    window.setTimeout(() => this.dispatchEvent(new Event("scroll")), 0);
  };
}

function renderLargeRegistry() {
  const rows: ToolRegistryVirtualRow[] = Array.from({ length: 160 }, (_, index) => ({
    key: `tool:tool-${index}:bundle-${Math.floor(index / 20)}`,
    kind: "tool",
    tool: { id: `tool-${index}`, name: `Tool ${index}` } as ToolRegistryItem,
    position: index + 1,
    total: 160,
    isLastInGroup: index % 20 === 19,
  }));
  const onActivateTool = vi.fn();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(
      <ToolRegistryVirtualList
        rows={rows}
        className="tool-list"
        ariaLabel="Tool registry"
        onActivateTool={onActivateTool}
        renderRow={(row) => row.kind === "tool" ? <button type="button">{row.tool.name}</button> : <h2>{row.group.label}</h2>}
      />,
    );
  });
  return { container: host, onActivateTool };
}

afterEach(async () => {
  if (root) {
    await act(async () => root?.unmount());
  }
  host?.remove();
  root = null;
  host = null;
  if (originalGetBoundingClientRect) {
    HTMLElement.prototype.getBoundingClientRect = originalGetBoundingClientRect;
    originalGetBoundingClientRect = null;
  }
  if (originalDimensionDescriptors) {
    for (const [property, descriptor] of originalDimensionDescriptors) {
      if (descriptor) Object.defineProperty(HTMLElement.prototype, property, descriptor);
      else Reflect.deleteProperty(HTMLElement.prototype, property);
    }
    originalDimensionDescriptors = null;
    if (originalElementScrollTo) {
      HTMLElement.prototype.scrollTo = originalElementScrollTo;
      originalElementScrollTo = null;
    } else {
      delete (HTMLElement.prototype as { scrollTo?: unknown }).scrollTo;
    }
  }
});

describe("Tool permission group disclosure", () => {
  it("does not mount hidden controls and preserves expansion across route rerenders", async () => {
    const container = renderDisclosure();
    const details = container.querySelector("details");
    const summary = container.querySelector("summary");

    expect(details?.open).toBe(false);
    expect(container.querySelector('[data-testid="permission-row"]')).toBeNull();
    expect(permissionChildrenRenderCount).toBe(0);

    await act(async () => {
      summary?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    });
    expect(details?.open).toBe(true);
    expect(container.querySelector('[data-testid="permission-row"]')).not.toBeNull();
    expect(permissionChildrenRenderCount).toBeGreaterThan(0);

    await act(async () => {
      root?.render(<DisclosureHarness label="Package A updated" />);
    });
    expect(container.querySelector("details")?.open).toBe(true);
    expect(container.textContent).toContain("Package A updated");
    expect(container.querySelector('[data-testid="permission-row"]')).not.toBeNull();

    await act(async () => {
      container.querySelector("summary")?.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
    });
    expect(container.querySelector("details")?.open).toBe(false);
    expect(container.querySelector('[data-testid="permission-row"]')).toBeNull();
  });

  it("mounts filtered results while searching and removes them when the search clears", async () => {
    const container = renderDisclosure({ forceOpen: true });
    expect(container.querySelector("details")?.open).toBe(true);
    expect(container.querySelector('[data-testid="permission-row"]')).not.toBeNull();

    await act(async () => {
      container.querySelector("details")?.dispatchEvent(new Event("toggle"));
    });
    await act(async () => {
      root?.render(<DisclosureHarness forceOpen={false} />);
    });
    expect(container.querySelector("details")?.open).toBe(false);
    expect(container.querySelector('[data-testid="permission-row"]')).toBeNull();
  });
});

describe("Tool registry virtualization", () => {
  it("keeps only a measured window mounted and lets End reach the final tool", async () => {
    stubRegistryViewport();
    const { container, onActivateTool } = renderLargeRegistry();
    const viewport = container.querySelector<HTMLElement>('[role="region"][aria-label="Tool registry"]');
    const mountedRows = container.querySelectorAll("[data-tool-row-index]");

    expect(viewport?.clientHeight).toBe(440);
    expect(viewport?.scrollHeight).toBeGreaterThan(viewport?.clientHeight ?? 0);
    expect(mountedRows.length).toBeGreaterThan(0);
    expect(mountedRows.length).toBeLessThan(40);
    expect(container.textContent).not.toContain("Tool 159");

    const firstButton = container.querySelector<HTMLButtonElement>('[data-tool-row-index="0"] button');
    expect(firstButton).not.toBeNull();
    await act(async () => {
      firstButton?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
    });
    expect(document.activeElement?.closest("[data-tool-row-index]")?.getAttribute("data-tool-row-index")).toBe("1");

    await act(async () => {
      container.querySelector<HTMLElement>('[data-tool-row-index="1"] button')
        ?.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true, cancelable: true }));
      await new Promise<void>((resolve) => window.setTimeout(resolve, 20));
    });

    expect(onActivateTool).toHaveBeenCalledWith(expect.objectContaining({ id: "tool-159" }));
    expect(elementScrollCallCount).toBeGreaterThan(0);
    expect(maxRequestedScrollTop).toBeGreaterThan(0);
  });
});
