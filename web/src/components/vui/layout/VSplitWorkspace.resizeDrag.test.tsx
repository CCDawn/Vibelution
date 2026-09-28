/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { VSplitWorkspace } from "./VSplitWorkspace";

/**
 * Wave 5B drag discipline (borrowed from zai-org/ZCode WorkbenchSplitDivider,
 * Apache-2.0): pointer moves must never enter React state — the hook writes
 * --pane-w-* straight onto the registered container — and pointerup commits
 * state exactly once (pointercancel included). The handle's aria-valuenow only
 * changes on React renders, so staying stale mid-drag proves the subtree did
 * not re-render while the variable moved.
 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;

async function renderWorkspace(): Promise<void> {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(() => root!.render(
    <VSplitWorkspace
      resize={{ layoutId: "drag-discipline" }}
      sidebar={<div>list</div>}
      main={<div>detail</div>}
    />,
  ));
}

function splitContainer(): HTMLElement {
  return document.querySelector('[data-vui-resizable="true"]') as HTMLElement;
}

function resizeHandle(): HTMLElement {
  return document.querySelector('[data-vui-layout-handle="resize"]') as HTMLElement;
}

function fakePointerEvent(type: string, clientX: number): Event {
  const event = new Event(type, { bubbles: true });
  Object.defineProperty(event, "button", { value: 0 });
  Object.defineProperty(event, "clientX", { value: clientX });
  return event;
}

async function nextFrame(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 24));
  });
}

function persistedSidebarWidth(): number {
  const persisted = JSON.parse(
    window.localStorage.getItem("vibelution.pane-layouts.v1") ?? "{}",
  ) as Record<string, Record<string, number>>;
  return persisted["drag-discipline"]?.sidebar ?? -1;
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(async () => {
  if (root) {
    await act(() => root!.unmount());
    root = null;
  }
  document.body.innerHTML = "";
});

describe("VSplitWorkspace Wave 5B drag discipline", () => {
  it("writes the variable during drag without re-rendering and commits once on pointerup", async () => {
    await renderWorkspace();
    expect(splitContainer().style.getPropertyValue("--pane-w-sidebar")).toBe("320px");
    expect(resizeHandle().getAttribute("aria-valuenow")).toBe("320");
    expect(resizeHandle().getAttribute("data-active")).toBe("false");

    await act(() => {
      resizeHandle().dispatchEvent(fakePointerEvent("pointerdown", 100));
      return Promise.resolve();
    });
    // Drag start marks the handle active (single render, width untouched).
    expect(resizeHandle().getAttribute("data-active")).toBe("true");
    expect(splitContainer().style.getPropertyValue("--pane-w-sidebar")).toBe("320px");

    await act(() => {
      window.dispatchEvent(fakePointerEvent("pointermove", 140));
      window.dispatchEvent(fakePointerEvent("pointermove", 160));
      window.dispatchEvent(fakePointerEvent("pointermove", 180));
      return Promise.resolve();
    });
    await nextFrame();
    // Moves bypass React: the container variable moved, the React-rendered
    // aria value stayed at the drag-start width (zero re-renders).
    expect(splitContainer().style.getPropertyValue("--pane-w-sidebar")).toBe("400px");
    expect(resizeHandle().getAttribute("aria-valuenow")).toBe("320");

    await act(() => {
      window.dispatchEvent(fakePointerEvent("pointerup", 180));
      return Promise.resolve();
    });
    // pointerup commits once: state, DOM variable and persistence converge.
    expect(splitContainer().style.getPropertyValue("--pane-w-sidebar")).toBe("400px");
    expect(resizeHandle().getAttribute("aria-valuenow")).toBe("400");
    expect(resizeHandle().getAttribute("data-active")).toBe("false");
    expect(persistedSidebarWidth()).toBe(400);
  });

  it("commits state on pointercancel the same way as pointerup", async () => {
    await renderWorkspace();
    await act(() => {
      resizeHandle().dispatchEvent(fakePointerEvent("pointerdown", 0));
      return Promise.resolve();
    });
    await act(() => {
      window.dispatchEvent(fakePointerEvent("pointermove", 30));
      return Promise.resolve();
    });
    await nextFrame();
    expect(splitContainer().style.getPropertyValue("--pane-w-sidebar")).toBe("350px");
    expect(resizeHandle().getAttribute("aria-valuenow")).toBe("320");

    await act(() => {
      window.dispatchEvent(fakePointerEvent("pointercancel", 30));
      return Promise.resolve();
    });
    expect(splitContainer().style.getPropertyValue("--pane-w-sidebar")).toBe("350px");
    expect(resizeHandle().getAttribute("aria-valuenow")).toBe("350");
    expect(resizeHandle().getAttribute("data-active")).toBe("false");
    expect(persistedSidebarWidth()).toBe(350);
  });

  it("applies keyboard steps through the existing single-write state path", async () => {
    await renderWorkspace();
    await act(() => {
      resizeHandle().dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
      return Promise.resolve();
    });
    expect(splitContainer().style.getPropertyValue("--pane-w-sidebar")).toBe("344px");
    expect(resizeHandle().getAttribute("aria-valuenow")).toBe("344");
  });
});
