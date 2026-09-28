// @vitest-environment happy-dom
/**
 * VHoverCard uses the same idle intent-mount discipline as ShadcnTooltip
 * (React 19 #185): the turn rail renders 100+ hover-card triggers, so the
 * Radix overlay must only mount after pointer intent survives `openDelay`
 * (or keyboard focus). These tests pin that behavior for the hover card.
 */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VHoverCard } from "../../index";
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

function DenseHoverCardHost({ count }: { count: number }) {
  const [tick, setTick] = useState(0);
  return (
    <VuiProvider>
      <button type="button" data-testid="bump" onClick={() => setTick((value) => value + 1)}>
        bump {tick}
      </button>
      {Array.from({ length: count }, (_, index) => (
        <VHoverCard key={index} content={`preview-${index}`}>
          <button type="button">{`item-${index}`}</button>
        </VHoverCard>
      ))}
    </VuiProvider>
  );
}

describe("ShadcnHoverCard intent mount", () => {
  it("does not loop when a dense idle hover-card rail rerenders", () => {
    mount(<DenseHoverCardHost count={128} />);
    const bump = container.querySelector("[data-testid='bump']");
    expect(bump).toBeTruthy();
    expect(document.querySelectorAll("[data-vui='hover-card-content']").length).toBe(0);
    expect(() => {
      act(() => {
        for (let i = 0; i < 8; i += 1) {
          bump?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        }
      });
    }).not.toThrow();
    expect(container.querySelector("[data-testid='bump']")?.textContent).toContain("bump 8");
    expect(document.querySelectorAll("[data-vui='hover-card-content']").length).toBe(0);
  });

  it("mounts and opens only after the pointer wait elapses", () => {
    vi.useFakeTimers();
    mount(
      <VuiProvider>
        <VHoverCard content="turn-preview">
          <button type="button">host</button>
        </VHoverCard>
      </VuiProvider>,
    );

    const host = container.querySelector("button");
    expect(host?.getAttribute("data-slot")).toBe("hover-card-trigger");
    expect(document.querySelector("[data-vui='hover-card-content']")).toBeNull();

    act(() => {
      // React maps onPointerEnter to bubbling pointerover, not pointerenter.
      if (host) pointerOver(host);
    });
    expect(document.querySelector("[data-vui='hover-card-content']")).toBeNull();

    act(() => {
      vi.advanceTimersByTime(119);
    });
    expect(document.querySelector("[data-vui='hover-card-content']")).toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(document.querySelector("[data-vui='hover-card-content']")?.textContent ?? "").toContain(
      "turn-preview",
    );
  });

  it("does not open when the pointer leaves before openDelay", () => {
    vi.useFakeTimers();
    mount(
      <VuiProvider>
        <VHoverCard content="turn-preview" openDelay={400}>
          <button type="button">host</button>
        </VHoverCard>
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
      vi.advanceTimersByTime(400);
    });
    expect(document.querySelector("[data-vui='hover-card-content']")).toBeNull();
  });

  it("opens on keyboard focus without waiting for the hover delay", () => {
    vi.useFakeTimers();
    mount(
      <VuiProvider>
        <VHoverCard content="turn-preview" openDelay={400}>
          <button type="button">host</button>
        </VHoverCard>
      </VuiProvider>,
    );

    const host = container.querySelector("button");
    act(() => {
      host?.focus();
    });
    expect(document.querySelector("[data-vui='hover-card-content']")?.textContent ?? "").toContain(
      "turn-preview",
    );
  });
});
