// @vitest-environment happy-dom
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { useComposedRefs } from "./radixComposeRefs";

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

function IdentityHost({
  onIdentity,
}: {
  onIdentity: (ref: (node: HTMLDivElement | null) => void) => void;
}) {
  const [tick, setTick] = useState(0);
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const composed = useComposedRefs<HTMLDivElement | null>(setNode);
  onIdentity(composed);
  return (
    <div>
      <div ref={composed} data-tick={tick} />
      <button type="button" onClick={() => setTick((value) => value + 1)}>
        bump
      </button>
      <span data-testid="node-bound">{node ? "yes" : "no"}</span>
    </div>
  );
}

describe("stable radix compose-refs shim", () => {
  it("keeps useComposedRefs identity across unrelated rerenders", () => {
    const identities: Array<(node: HTMLDivElement | null) => void> = [];
    mount(
      <IdentityHost
        onIdentity={(ref) => {
          identities.push(ref);
        }}
      />,
    );

    const button = container.querySelector("button");
    expect(button).toBeTruthy();
    act(() => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(identities.length).toBeGreaterThan(2);
    expect(new Set(identities).size).toBe(1);
    expect(container.querySelector("[data-testid='node-bound']")?.textContent).toBe("yes");
  });
});
