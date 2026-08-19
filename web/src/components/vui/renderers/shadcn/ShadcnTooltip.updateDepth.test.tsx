// @vitest-environment happy-dom
/**
 * Regression for workbench React #185 (Maximum update depth exceeded) inside
 * Radix overlay `setRef`. Chat/index chrome mounts many VTooltip / VButton
 * tooltip instances; React 19 re-attaches composed refs when the callback
 * identity churns, and state-setter refs then loop until React bails out.
 */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

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
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
});

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
  it("does not loop when a dense tooltip list rerenders", () => {
    mount(<DenseTooltipHost count={32} />);
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
    expect(container.querySelector("button")?.textContent).toBeTruthy();
  });
});
