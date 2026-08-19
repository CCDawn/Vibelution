/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { TeamsWorkbenchInspectorOverlay } from "./renderTeamsWorkbenchBoardPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const styles: Record<string, string> = {
  boardInspectorOverlayBackdrop: "backdrop",
  boardInspectorOverlayPanel: "panel",
  boardInspectorOverlayHeader: "header",
  boardInspectorOverlayBody: "body",
};

function keydown(target: Element, key: string) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

describe("TeamsWorkbenchInspectorOverlay", () => {
  let host: HTMLDivElement | null = null;
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    host = null;
    root = null;
  });

  function renderOverlay(onDismiss: () => void) {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root?.render(
        <TeamsWorkbenchInspectorOverlay
          styles={styles}
          label="Detail panel"
          dismissLabel="Close detail panel"
          onDismiss={onDismiss}
        >
          <button type="button" data-testid="inner-control">
            Inner control
          </button>
        </TeamsWorkbenchInspectorOverlay>,
      );
    });
    const backdrop = document.body.querySelector<HTMLElement>(
      '[data-vui-region="teams-inspector-overlay-backdrop"]',
    );
    if (!backdrop) {
      throw new Error("backdrop not rendered");
    }
    return { backdrop };
  }

  it("exposes the backdrop as a focusable dismiss control", () => {
    const { backdrop } = renderOverlay(() => undefined);
    expect(backdrop.getAttribute("role")).toBe("button");
    expect(backdrop.getAttribute("tabindex")).toBe("0");
    expect(backdrop.getAttribute("aria-label")).toBe("Close detail panel");
  });

  it("closes on Escape from the backdrop and from inside the panel", () => {
    let dismissals = 0;
    const { backdrop } = renderOverlay(() => {
      dismissals += 1;
    });
    keydown(backdrop, "Escape");
    expect(dismissals).toBe(1);
    const inner = document.body.querySelector<HTMLElement>('[data-testid="inner-control"]');
    keydown(inner as HTMLElement, "Escape");
    expect(dismissals).toBe(2);
  });

  it("closes on Enter/Space only when the backdrop itself is the key target", () => {
    let dismissals = 0;
    const { backdrop } = renderOverlay(() => {
      dismissals += 1;
    });
    keydown(backdrop, "Enter");
    keydown(backdrop, " ");
    expect(dismissals).toBe(2);
    const inner = document.body.querySelector<HTMLElement>('[data-testid="inner-control"]');
    keydown(inner as HTMLElement, "Enter");
    keydown(inner as HTMLElement, " ");
    expect(dismissals).toBe(2);
  });

  it("keeps click-to-dismiss on the backdrop but not on the panel", () => {
    let dismissals = 0;
    const { backdrop } = renderOverlay(() => {
      dismissals += 1;
    });
    act(() => {
      backdrop.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(dismissals).toBe(1);
    const panel = document.body.querySelector<HTMLElement>('[data-vui-region="teams-inspector-overlay"]');
    act(() => {
      panel?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(dismissals).toBe(1);
    expect(panel?.getAttribute("role")).toBe("region");
    expect(panel?.getAttribute("aria-label")).toBe("Detail panel");
  });
});
