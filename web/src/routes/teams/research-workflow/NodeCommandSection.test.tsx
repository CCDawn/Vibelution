/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { NodeCommandSection } from "./NodeCommandSection";

function offer(overrides: Partial<CommandOffer> = {}): CommandOffer {
  return {
    command: "start_node",
    idempotencyKey: "key-1",
    label: "启动节点",
    available: true,
    reasonCode: "",
    blockerIds: [],
    ...overrides,
  } as CommandOffer;
}

async function renderSection(onOffer: (offer: CommandOffer) => Promise<void>) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<NodeCommandSection offers={[offer()]} busy={false} onOffer={onOffer} />);
  });
  return { container, root };
}

describe("NodeCommandSection", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("shows an inline productized error when the offer action fails", async () => {
    const rendered = await renderSection(async () => {
      throw new Error("source search is still running");
    });
    root = rendered.root;
    const { container } = rendered;

    const button = container.querySelector("button");
    expect(button).toBeTruthy();
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("资料搜索仍在进行");
  });

  it("clears the inline error when the retried action succeeds", async () => {
    let attempts = 0;
    const rendered = await renderSection(async () => {
      attempts += 1;
      if (attempts === 1) {
        throw new Error("backend unavailable");
      }
    });
    root = rendered.root;
    const { container } = rendered;
    const button = container.querySelector("button");

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("操作未完成");

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});
