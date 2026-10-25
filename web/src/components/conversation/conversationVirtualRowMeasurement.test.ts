// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Virtualizer } from "@tanstack/react-virtual";
import { measureConversationVirtualRow } from "./conversationVirtualRowMeasurement";

const cleanups: Array<() => void> = [];
const observers: Observer[] = [];
class Observer {
  elements = new Set<Element>();
  constructor(private readonly callback: ResizeObserverCallback) { observers.push(this); }
  observe = (element: Element) => { this.elements.add(element); };
  unobserve = (element: Element) => { this.elements.delete(element); };
  disconnect = () => { this.elements.clear(); };
  emit(element: Element, height: number) {
    this.callback([{ target: element, borderBoxSize: [{ inlineSize: 500, blockSize: height }] }] as unknown as ResizeObserverEntry[], this as unknown as ResizeObserver);
  }
}

beforeEach(() => { observers.length = 0; vi.stubGlobal("ResizeObserver", Observer); });
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()); vi.unstubAllGlobals(); });

function fixture({ initialize = true, animationFrame = false } = {}) {
  const keys = ["row-a", "row-b"];
  const scroll = document.createElement("div");
  const row = document.createElement("div");
  row.dataset.index = "0";
  scroll.append(row);
  document.body.append(scroll);
  const virtualizer = new Virtualizer<HTMLDivElement, HTMLDivElement>({
    count: keys.length, getScrollElement: () => scroll,
    getItemKey: (index) => keys[index], estimateSize: () => 160,
    initialRect: { width: 500, height: 600 }, scrollToFn: () => {},
    observeElementRect: (_instance, callback) => { callback({ width: 500, height: 600 }); return () => {}; },
    observeElementOffset: (_instance, callback) => { callback(0, false); return () => {}; },
    measureElement: measureConversationVirtualRow,
    useAnimationFrameWithResizeObserver: animationFrame,
  });
  let unmount = () => {};
  const mount = () => {
    unmount = virtualizer._didMount();
    virtualizer._willUpdate();
  };
  if (initialize) mount();
  virtualizer.getTotalSize();
  cleanups.push(() => { unmount(); scroll.remove(); });
  return { keys, row, virtualizer, mount };
}

describe("conversation virtual row measurement", () => {
  it("observes a new row without synchronously reading its geometry", () => {
    const { row, virtualizer } = fixture();
    const readHeight = vi.fn(() => { throw new Error("forced initial layout"); });
    Object.defineProperty(row, "offsetHeight", { get: readHeight });

    virtualizer.measureElement(row);

    expect(readHeight).not.toHaveBeenCalled();
    expect(virtualizer.getTotalSize()).toBe(320);
    const observer = observers.find((item) => item.elements.has(row));
    expect(observer).toBeDefined();
    observer!.emit(row, 213.4);
    expect(virtualizer.itemSizeCache.get("row-a")).toBe(213);
    expect(virtualizer.getTotalSize()).toBe(373);
    observer!.emit(row, 0);
    virtualizer.measureElement(row);
    expect(virtualizer.itemSizeCache.get("row-a")).toBe(0);
    expect(virtualizer.getTotalSize()).toBe(160);
  });

  it("retains stable-key measurements after prepend and accepts later height changes", () => {
    const { keys, row, virtualizer } = fixture();
    Object.defineProperty(row, "offsetHeight", { get: () => { throw new Error("cached row must not force layout"); } });
    virtualizer.measureElement(row);
    const observer = observers.find((item) => item.elements.has(row))!;
    observer.emit(row, 220);
    keys.unshift("row-earlier");
    row.dataset.index = "1";
    virtualizer.setOptions({ ...virtualizer.options, count: keys.length });
    virtualizer.getTotalSize();

    virtualizer.measureElement(row);
    expect(virtualizer.itemSizeCache.get("row-a")).toBe(220);
    observer.emit(row, 405);
    expect(virtualizer.itemSizeCache.get("row-a")).toBe(405);
    expect(virtualizer.getTotalSize()).toBe(725);
  });

  it("uses the library's synchronous fallback when ResizeObserver is unavailable", () => {
    const { row, virtualizer } = fixture();
    vi.stubGlobal("ResizeObserver", undefined);
    Object.defineProperty(row, "offsetHeight", { get: () => 180 });
    expect(measureConversationVirtualRow(row, undefined, virtualizer)).toBe(180);
  });

  it("registers an early ref after the virtualizer acquires its target window", () => {
    const { row, virtualizer, mount } = fixture({ initialize: false });
    Object.defineProperty(row, "offsetHeight", { get: () => { throw new Error("early ref must not force layout"); } });
    expect(virtualizer.targetWindow).toBeNull();
    virtualizer.measureElement(row);
    expect(virtualizer.elementsCache.get("row-a")).toBe(row);
    expect(observers).toHaveLength(0);

    mount();
    const observer = observers.find((item) => item.elements.has(row))!;
    expect(observer).toBeDefined();
    observer.emit(row, 240);
    expect(virtualizer.itemSizeCache.get("row-a")).toBe(240);
  });

  it("applies observer sizes on the configured animation frame, including later growth", () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.push(callback); return frames.length; });
    const { row, virtualizer } = fixture({ animationFrame: true });
    Object.defineProperty(row, "offsetHeight", { get: () => { throw new Error("observer must own row geometry"); } });
    virtualizer.measureElement(row);
    const observer = observers.find((item) => item.elements.has(row))!;

    observer.emit(row, 210);
    expect(virtualizer.getTotalSize()).toBe(320);
    frames.shift()!(0);
    expect(virtualizer.getTotalSize()).toBe(370);
    observer.emit(row, 330);
    expect(virtualizer.getTotalSize()).toBe(370);
    frames.shift()!(16);
    expect(virtualizer.getTotalSize()).toBe(490);
  });
});
