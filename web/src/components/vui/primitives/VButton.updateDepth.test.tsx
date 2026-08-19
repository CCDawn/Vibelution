// @vitest-environment happy-dom
/**
 * Production chat chrome wraps many VButton `title`/`tooltip` instances, and
 * composer controls nest those buttons inside VPopover asChild. Lazy VTooltip
 * + Suspense reused the same button element as fallback and children, which
 * remounted Radix overlay trigger hosts until React 19 threw #185.
 */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { VButton } from "./VButton";
import { VPopover } from "./VPopover";
import { VuiProvider } from "../VuiProvider";

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
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
});

function ChatChromeHost({ count }: { count: number }) {
  const [tick, setTick] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <VuiProvider>
      <button type="button" data-testid="bump" onClick={() => setTick((value) => value + 1)}>
        bump {tick}
      </button>
      <VPopover
        open={menuOpen}
        onOpenChange={setMenuOpen}
        trigger={(
          <VButton type="button" title={`model · effort ${tick}`}>
            model · effort
          </VButton>
        )}
      >
        <div>reasoning options</div>
      </VPopover>
      {Array.from({ length: count }, (_, index) => (
        <VButton key={index} type="button" tooltip={`tip-${index}`}>
          {`item-${index}`}
        </VButton>
      ))}
    </VuiProvider>
  );
}

describe("VButton tooltip React 19 update depth", () => {
  it("does not loop when dense titled buttons and a popover trigger rerender", () => {
    mount(<ChatChromeHost count={32} />);
    const bump = container.querySelector("[data-testid='bump']");
    expect(bump).toBeTruthy();
    expect(() => {
      act(() => {
        for (let i = 0; i < 8; i += 1) {
          bump?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        }
      });
    }).not.toThrow();
    expect(container.querySelector("[data-testid='bump']")?.textContent).toContain("bump 8");
    expect(container.querySelectorAll('button[data-vui="button"]').length).toBeGreaterThan(8);
  });
});
