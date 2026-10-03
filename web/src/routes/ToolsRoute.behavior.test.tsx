/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { ToolPermissionGroupDisclosure } from "./ToolsRoute";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
let root: Root | null = null;
let permissionChildrenRenderCount = 0;

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

afterEach(async () => {
  if (root) {
    await act(async () => root?.unmount());
  }
  host?.remove();
  root = null;
  host = null;
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
