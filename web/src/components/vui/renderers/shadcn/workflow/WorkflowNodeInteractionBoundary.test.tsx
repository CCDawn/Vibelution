/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { WorkflowNodeInteractionBoundary } from "./WorkflowNodeInteractionBoundary";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("WorkflowNodeInteractionBoundary", () => {
  it("activates the visible node button without relying on React Flow bubbling", async () => {
    const onActivate = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <WorkflowNodeInteractionBoundary onActivate={onActivate}>
          <button type="button" onClick={(event) => event.stopPropagation()}>
            协议冻结
          </button>
        </WorkflowNodeInteractionBoundary>,
      );
    });

    const button = container.querySelector("button") as HTMLButtonElement;
    await act(async () => button.click());
    expect(onActivate).toHaveBeenCalledTimes(1);

    await act(async () => {
      button.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    expect(onActivate).toHaveBeenCalledTimes(2);

    await act(async () => {
      root.unmount();
      container.remove();
    });
  });
});
