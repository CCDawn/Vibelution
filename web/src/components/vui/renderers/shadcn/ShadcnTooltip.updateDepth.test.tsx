// @vitest-environment happy-dom
/**
 * Regression for workbench React #185 (Maximum update depth exceeded) inside
 * Radix overlay `setRef`. Chat session rows each wrap two VTooltip hosts;
 * mounting Radix Trigger/Popper on every idle row calls state-setter refs
 * during the same commit, and ~25 sessions already exceed React 19's nested
 * update limit. Idle tips stay host-only until pointer/focus intent.
 */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VTooltip } from "../../index";
import { VuiProvider } from "../../VuiProvider";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLElement;

function mount(node: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root?.render(node);
  });
}

afterEach(() => {
  vi.useRealTimers();
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
});

function pointerOver(host: Element) {
  host.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
}

function pointerOut(host: Element) {
  host.dispatchEvent(new MouseEvent("pointerout", { bubbles: true, relatedTarget: document.body }));
}

function DenseTooltipHost({ count }: { count: number }) {
  const [tick, setTick] = useState(0);
  return (
    <VuiProvider>
      <button type="button" data-testid="bump" onClick={() => setTick((value) => value + 1)}>
        bump {tick}
      </button>
      {Array.from({ length: count }, (_, index) => (
        <VTooltip key={index} content={`tip-${index}`}>
          <button type="button">{`item-${index}`}</button>
        </VTooltip>
      ))}
    </VuiProvider>
  );
}

describe("ShadcnTooltip React 19 update depth", () => {
  it("does not loop when a dense idle tooltip list rerenders", () => {
    mount(<DenseTooltipHost count={64} />);
    const bump = container.querySelector("[data-testid='bump']");
    expect(bump).toBeTruthy();
    expect(document.querySelectorAll("[data-vui='tooltip-content']").length).toBe(0);
    expect(() => {
      act(() => {
        for (let i = 0; i < 8; i += 1) {
          bump?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        }
      });
    }).not.toThrow();
    expect(container.querySelector("[data-testid='bump']")?.textContent).toContain("bump 8");
    expect(container.querySelector("button")?.textContent).toBeTruthy();
    expect(document.querySelectorAll("[data-vui='tooltip-content']").length).toBe(0);
  });

  it("keeps the trigger slot on the idle host until the pointer wait elapses", () => {
    vi.useFakeTimers();
    mount(
      <VuiProvider>
        <VTooltip content="hello-tip">
          <button type="button">host</button>
        </VTooltip>
      </VuiProvider>,
    );

    const host = container.querySelector("button");
    expect(host?.getAttribute("data-slot")).toBe("tooltip-trigger");
    expect(document.querySelector("[data-vui='tooltip-content']")).toBeNull();

    act(() => {
      // React maps onPointerEnter to bubbling pointerover, not pointerenter.
      if (host) pointerOver(host);
    });
    expect(document.querySelector("[data-vui='tooltip-content']")).toBeNull();

    act(() => {
      vi.advanceTimersByTime(319);
    });
    expect(document.querySelector("[data-vui='tooltip-content']")).toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    const trigger = container.querySelector("[data-slot='tooltip-trigger']");
    expect(trigger?.getAttribute("data-state")).toBeTruthy();
    expect(document.querySelector("[data-vui='tooltip-content']")?.textContent ?? "").toContain("hello-tip");
  });

  it("does not open when the pointer leaves before the delay", () => {
    vi.useFakeTimers();
    mount(
      <VuiProvider>
        <VTooltip content="hello-tip" delay={500}>
          <button type="button">host</button>
        </VTooltip>
      </VuiProvider>,
    );

    const host = container.querySelector("button");
    act(() => {
      if (host) pointerOver(host);
    });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    act(() => {
      if (host) pointerOut(host);
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(document.querySelector("[data-vui='tooltip-content']")).toBeNull();
  });

  it("opens on keyboard focus without waiting for the hover delay", () => {
    vi.useFakeTimers();
    mount(
      <VuiProvider>
        <VTooltip content="hello-tip" delay={500}>
          <button type="button">host</button>
        </VTooltip>
      </VuiProvider>,
    );

    const host = container.querySelector("button");
    act(() => {
      host?.focus();
    });
    expect(document.querySelector("[data-vui='tooltip-content']")?.textContent ?? "").toContain("hello-tip");
  });
});
