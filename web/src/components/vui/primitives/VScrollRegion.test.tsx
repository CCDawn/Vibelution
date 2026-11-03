/** @vitest-environment happy-dom */
import React, { act, createRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createPortal } from "react-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VScrollRegion, type VScrollRegionProps } from "./VScrollRegion";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLDivElement;

function renderRegion(props: VScrollRegionProps = {}, ref?: React.Ref<HTMLDivElement>, portal?: React.ReactNode) {
  if (!root) {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
  }
  act(() => root?.render(<><VScrollRegion {...props} ref={ref} />{portal}</>));
  const element = host.querySelector<HTMLDivElement>('[data-vui="scroll-region"]');
  if (!element) throw new Error("Scroll region missing");
  Object.defineProperties(element, {
    clientHeight: { configurable: true, value: 100 },
    scrollHeight: { configurable: true, value: 500 },
    offsetWidth: { configurable: true, value: 200 },
    clientWidth: { configurable: true, value: 194 },
    clientLeft: { configurable: true, value: 0 },
  });
  element.getBoundingClientRect = () => ({
    x: 10, y: 20, left: 10, top: 20, right: 210, bottom: 120, width: 200, height: 100,
    toJSON: () => ({}),
  });
  return element;
}

function pointer(type: string, values: Record<string, string | number | boolean> = {}) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  for (const [key, value] of Object.entries({
    button: 0, isPrimary: true, pointerType: "mouse", pointerId: 7, clientX: 208, clientY: 50,
    ...values,
  })) Object.defineProperty(event, key, { value });
  return event;
}

function dispatch(target: EventTarget, event: Event) {
  act(() => { target.dispatchEvent(event); });
}

function advance(milliseconds: number) {
  act(() => { vi.advanceTimersByTime(milliseconds); });
}

function expectState(element: HTMLDivElement, active: boolean, dragging = false) {
  expect(element.dataset.scrollActive).toBe(String(active));
  expect(element.dataset.scrollDragging).toBe(String(dragging));
}

beforeEach(() => vi.useFakeTimers());

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  host?.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("VScrollRegion", () => {
  it.each(["wheel", "touchmove", "keydown"])("observes physical %s from a sibling React portal", (type) => {
    const element = renderRegion();
    renderRegion({}, undefined, createPortal(<button>portaled task</button>, element));
    const button = element.querySelector("button")!;
    const event = type === "wheel" ? new WheelEvent(type, { bubbles: true, deltaY: 40 })
      : type === "keydown" ? new KeyboardEvent(type, { bubbles: true, key: "PageDown" })
        : new Event(type, { bubbles: true });
    dispatch(button, event);
    advance(0);
    expectState(element, true);
    advance(800);
    expectState(element, false);
  });

  it("respects cancelled input and editing keys inside a sibling portal", () => {
    const element = renderRegion();
    renderRegion({}, undefined, createPortal(<input />, element));
    const input = element.querySelector("input")!;
    input.addEventListener("wheel", event => event.preventDefault());
    dispatch(input, new WheelEvent("wheel", { bubbles: true, cancelable: true }));
    dispatch(input, new KeyboardEvent("keydown", { bubbles: true, key: "Home" }));
    advance(0);
    expectState(element, false);
  });

  it("cancels deferred portal input on unmount and preserves React callback cancellation", () => {
    const element = renderRegion({ onWheel: event => event.preventDefault() });
    dispatch(element, new WheelEvent("wheel", { bubbles: true, cancelable: true }));
    advance(0);
    expectState(element, false);
    renderRegion({}, undefined, createPortal(<span>task</span>, element));
    dispatch(element.querySelector("span")!, new WheelEvent("wheel", { bubbles: true }));
    expect(vi.getTimerCount()).toBe(1);
    act(() => root?.unmount());
    root = null;
    expect(vi.getTimerCount()).toBe(0);
    advance(800);
  });

  it("shows on wheel, extends from the last user input, and hides after 800ms", () => {
    const element = renderRegion();
    expectState(element, false);
    dispatch(element, new WheelEvent("wheel", { bubbles: true, deltaY: 10 }));
    expectState(element, true);
    advance(799);
    expectState(element, true);
    dispatch(element, new WheelEvent("wheel", { bubbles: true, deltaY: 10 }));
    advance(799);
    expectState(element, true);
    advance(1);
    expectState(element, false);
  });

  it("shows for touch movement and scrolling keys without preventing native input", () => {
    const element = renderRegion({ tabIndex: 0 });
    for (const event of [
      new Event("touchmove", { bubbles: true, cancelable: true }),
      ...["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].map((key) => (
        new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true })
      )),
    ]) {
      dispatch(element, event);
      expectState(element, true);
      expect(event.defaultPrevented).toBe(false);
      advance(800);
      expectState(element, false);
    }
  });

  it("leaves programmatic and streaming scroll hidden and does not prolong user activity", () => {
    const onScroll = vi.fn();
    const element = renderRegion({ onScroll });
    for (let i = 0; i < 4; i += 1) {
      element.scrollTop += 20;
      dispatch(element, new Event("scroll"));
      advance(300);
      expectState(element, false);
    }
    dispatch(element, new WheelEvent("wheel", { bubbles: true, deltaY: 10 }));
    advance(799);
    dispatch(element, new Event("scroll"));
    advance(1);
    expectState(element, false);
    expect(element.scrollTop).toBe(80);
    expect(onScroll).toHaveBeenCalledTimes(5);
  });

  it.each(["pointerup", "pointercancel", "blur"])("keeps a held native thumb visible until window %s then waits 800ms", (endEvent) => {
    const element = renderRegion();
    dispatch(element, pointer("pointerdown"));
    expectState(element, true, true);
    advance(2400);
    expectState(element, true, true);
    dispatch(window, endEvent === "blur" ? new Event("blur") : pointer(endEvent));
    expectState(element, true);
    advance(799);
    expectState(element, true);
    advance(1);
    expectState(element, false);
  });

  it("uses the measured left gutter for RTL and ignores another pointer's release", () => {
    const element = renderRegion({ dir: "rtl" });
    Object.defineProperty(element, "clientLeft", { configurable: true, value: 6 });
    dispatch(element, pointer("pointerdown", { clientX: 12 }));
    expectState(element, true, true);
    dispatch(window, pointer("pointerup", { pointerId: 8 }));
    advance(1200);
    expectState(element, true, true);
    dispatch(window, pointer("pointerup"));
    advance(800);
    expectState(element, false);
  });

  it.each([1, 1.5])("keeps a rounded fractional LTR border separate from the right gutter at scale %s", (scale) => {
    const element = renderRegion({ style: { borderLeftWidth: 1.5, borderRightWidth: 1.5 } });
    Object.defineProperties(element, {
      clientWidth: { configurable: true, value: 191 },
      clientLeft: { configurable: true, value: 2 },
    });
    element.getBoundingClientRect = () => ({
      x: 10, y: 20, left: 10, top: 20, right: 10 + 200 * scale, bottom: 20 + 100 * scale,
      width: 200 * scale, height: 100 * scale, toJSON: () => ({}),
    });
    dispatch(element, pointer("pointerdown", { clientX: 10 + 4 * scale }));
    expectState(element, false);
    dispatch(element, pointer("pointerdown", { clientX: 10 + 196 * scale }));
    expectState(element, true, true);
  });

  it("ignores borders, content, non-primary input and reserved gutter without overflow", () => {
    const element = renderRegion({ style: { borderLeftWidth: 2, borderRightWidth: 3 } });
    Object.defineProperties(element, {
      clientWidth: { configurable: true, value: 189 },
      clientLeft: { configurable: true, value: 2 },
    });
    for (const values of [
      { clientX: 11 }, { clientX: 209 }, { clientX: 100 }, { clientY: 121 },
      { button: 1 }, { isPrimary: false }, { pointerType: "touch" },
    ]) {
      dispatch(element, pointer("pointerdown", values));
      expectState(element, false);
    }
    Object.defineProperty(element, "scrollHeight", { configurable: true, value: 100 });
    dispatch(element, pointer("pointerdown", { clientX: 205 }));
    dispatch(element, new WheelEvent("wheel", { bubbles: true, deltaY: 10 }));
    dispatch(element, new KeyboardEvent("keydown", { key: "PageDown", bubbles: true }));
    expectState(element, false);
  });

  it("does not treat a zero-width overlay gutter as a thumb drag", () => {
    const element = renderRegion();
    Object.defineProperty(element, "clientWidth", { configurable: true, value: 200 });
    dispatch(element, pointer("pointerdown"));
    expectState(element, false);
  });

  it("ignores editing keys and unrelated keys while retaining consumer handlers", () => {
    const onKeyDown = vi.fn();
    const element = renderRegion({
      onKeyDown,
      children: <><input /><textarea /><select /><div contentEditable suppressContentEditableWarning><span>edit</span></div></>,
    });
    const inputs = element.querySelectorAll("input, textarea, select, span");
    inputs.forEach((input) => {
      dispatch(input, new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
      expectState(element, false);
    });
    dispatch(element, new KeyboardEvent("keydown", { key: "a", bubbles: true }));
    dispatch(element, new KeyboardEvent("keydown", { key: "Home", ctrlKey: true, bubbles: true }));
    expectState(element, false);
    expect(onKeyDown).toHaveBeenCalledTimes(inputs.length + 2);
  });

  it("ignores button activation and consumed keys while preserving native link scrolling", () => {
    const element = renderRegion({
      onKeyDown: (event) => { if (event.key === "PageDown") event.preventDefault(); },
      children: <><button><span>button</span></button><div role="button"><span>custom button</span></div><a href="#link">link</a></>,
    });
    for (const button of element.querySelectorAll("button span, [role='button'] span")) {
      for (const key of [" ", "Spacebar", "Enter"]) {
        dispatch(button, new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
        expectState(element, false);
      }
    }
    const button = element.querySelector("button")!;
    dispatch(button, new KeyboardEvent("keydown", { key: "PageDown", bubbles: true, cancelable: true }));
    expectState(element, false);
    dispatch(button, new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    expectState(element, true);
    advance(800);
    dispatch(element.querySelector("a")!, new KeyboardEvent("keydown", { key: " ", bubbles: true }));
    expectState(element, true);
  });

  it("forwards the actual div, native semantics and all existing callbacks", () => {
    const ref = createRef<HTMLDivElement>();
    const callbacks = {
      onWheel: vi.fn(), onTouchMove: vi.fn(), onKeyDown: vi.fn(), onPointerDown: vi.fn(), onScroll: vi.fn(),
    };
    const element = renderRegion({
      ...callbacks, role: "log", tabIndex: -1, "aria-label": "conversation", className: "timeline-height", children: <span>turn</span>,
    }, ref);
    expect(ref.current).toBe(element);
    expect(host.children).toHaveLength(1);
    expect(element.children).toHaveLength(1);
    expect(element.getAttribute("role")).toBe("log");
    expect(element.tabIndex).toBe(-1);
    expect(element.getAttribute("aria-label")).toBe("conversation");
    expect(element.classList.contains("timeline-height")).toBe(true);
    for (const event of [
      new WheelEvent("wheel", { bubbles: true }), new Event("touchmove", { bubbles: true }),
      new KeyboardEvent("keydown", { key: "End", bubbles: true }), pointer("pointerdown"), new Event("scroll"),
    ]) dispatch(element, event);
    Object.values(callbacks).forEach((callback) => expect(callback).toHaveBeenCalledOnce());

    const callbackRef = vi.fn();
    renderRegion({}, callbackRef);
    expect(ref.current).toBeNull();
    expect(callbackRef).toHaveBeenCalledWith(element);
    act(() => root?.unmount());
    root = null;
    expect(callbackRef.mock.calls.at(-1)?.[0]).toBeNull();
  });

  it("cleans the timer and drag listeners on unmount", () => {
    const removeListener = vi.spyOn(window, "removeEventListener");
    const element = renderRegion();
    dispatch(element, new WheelEvent("wheel", { bubbles: true }));
    dispatch(element, pointer("pointerdown"));
    act(() => root?.unmount());
    root = null;
    for (const type of ["pointerup", "pointercancel", "blur"]) {
      expect(removeListener).toHaveBeenCalledWith(type, expect.any(Function));
    }
    expect(vi.getTimerCount()).toBe(0);
    dispatch(window, pointer("pointerup"));
    expect(vi.getTimerCount()).toBe(0);
  });
});
