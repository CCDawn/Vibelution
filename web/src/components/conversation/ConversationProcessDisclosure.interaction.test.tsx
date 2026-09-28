/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { ConversationProcessDisclosure } from "./ConversationProcessDisclosure";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("makes a collapsed streaming trail inert and restores focus when it settles", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const render = (streaming: boolean) => root.render(
    <ConversationProcessDisclosure cells={[]} language="en" turnStreaming={streaming}>
      <button type="button">Tool action</button>
    </ConversationProcessDisclosure>,
  );
  try {
    await act(async () => render(true));
    const summary = host.querySelector("summary")!;
    const content = host.querySelector('div[aria-hidden="false"]')!;
    expect(content.hasAttribute("inert")).toBe(false);
    await act(async () => summary.click());
    expect(host.querySelector('div[aria-hidden="true"]')?.hasAttribute("inert")).toBe(true);
    // The live trail stays mounted after its collapse animation finishes.
    await act(async () => new Promise((resolve) => setTimeout(resolve, 320)));
    expect(host.querySelector("button")).not.toBeNull();
    expect(host.querySelector('div[aria-hidden="true"]')?.hasAttribute("inert")).toBe(true);
    await act(async () => summary.click());
    await act(async () => new Promise((resolve) => setTimeout(resolve, 40)));
    host.querySelector("button")!.focus();
    await act(async () => render(false));
    expect(document.activeElement).toBe(summary);
    expect(host.querySelector('div[aria-hidden="true"]')?.hasAttribute("inert")).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
