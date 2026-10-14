/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConversationSelectionQuoteMenu } from "../../conversation/ConversationSelectionQuoteMenu";
import type { SelectionToolbarAnchorRect } from "../../layout/selectionToolbarPosition";
import { VButton } from "./VButton";
import { VSelectionToolbar } from "./VSelectionToolbar";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const anchorRect: SelectionToolbarAnchorRect = {
  left: 300, top: 160, right: 350, bottom: 180, width: 50, height: 20,
};

let root: Root | null = null;
let host: HTMLDivElement | null = null;
let selectionFixture: HTMLDivElement | null = null;

function renderToolbar(content: React.ReactNode) {
  if (!host) {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  }
  act(() => root?.render(content));
  const toolbar = document.querySelector<HTMLDivElement>('[data-vui="selection-toolbar"]');
  if (!toolbar) throw new Error("Selection toolbar missing");
  return toolbar;
}

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  selectionFixture?.remove();
  document.getSelection()?.removeAllRanges();
  root = null;
  host = null;
  selectionFixture = null;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("VSelectionToolbar", () => {
  it("portals to the body and preserves selection and focus until an action click", () => {
    selectionFixture = document.createElement("div");
    const selectedText = document.createTextNode("selected words");
    const input = document.createElement("input");
    selectionFixture.append(selectedText, input);
    document.body.appendChild(selectionFixture);
    input.focus();
    const range = document.createRange();
    range.selectNodeContents(selectedText);
    document.getSelection()?.addRange(range);
    const onAction = vi.fn();
    const toolbar = renderToolbar(
      <VSelectionToolbar anchorRect={anchorRect} ariaLabel="Selection actions" className="custom-marker">
        <VButton onClick={onAction}>Quote</VButton>
      </VSelectionToolbar>,
    );

    expect(toolbar.parentElement).toBe(document.body);
    expect(host?.contains(toolbar)).toBe(false);
    expect(toolbar.getAttribute("role")).toBe("toolbar");
    expect(toolbar.getAttribute("aria-label")).toBe("Selection actions");
    expect(toolbar.classList.contains("custom-marker")).toBe(true);
    expect(document.activeElement).toBe(input);
    const action = toolbar.querySelector<HTMLButtonElement>("button")!;
    const mouseDown = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    act(() => action.dispatchEvent(mouseDown));
    expect(mouseDown.defaultPrevented).toBe(true);
    expect(document.getSelection()?.toString()).toBe("selected words");
    expect(document.activeElement).toBe(input);
    expect(onAction).not.toHaveBeenCalled();
    act(() => action.click());
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it("keeps the conversation action order, DOM boundary, and original callbacks", () => {
    const onSideChat = vi.fn();
    const onQuote = vi.fn();
    const onReference = vi.fn();
    const onCopy = vi.fn();
    const toolbar = renderToolbar(
      <ConversationSelectionQuoteMenu
        selectionRect={anchorRect}
        quoteLabel="Quote"
        copyLabel="Copy"
        referenceLabel="Reference"
        sideLabel="Side chat"
        onQuote={onQuote}
        onCopy={onCopy}
        onReference={onReference}
        onSideChat={onSideChat}
      />,
    );
    expect(toolbar.getAttribute("data-conversation-selection-menu")).toBe("1");
    expect(toolbar.classList.contains("selectionQuoteMenu")).toBe(true);
    const actions = Array.from(toolbar.querySelectorAll<HTMLButtonElement>("button"));
    expect(actions.map((action) => action.textContent)).toEqual(["Side chat", "Quote", "Reference", "Copy"]);
    for (const [index, callback] of [onSideChat, onQuote, onReference, onCopy].entries()) {
      act(() => actions[index].click());
      expect(callback).toHaveBeenCalledTimes(1);
    }
  });

  it("uses fallback geometry when unmeasured and flips below a selection near the top", () => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(1200);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(800);
    const toolbar = renderToolbar(
      <VSelectionToolbar anchorRect={anchorRect} ariaLabel="Selection actions"><VButton>Quote</VButton></VSelectionToolbar>,
    );
    expect(toolbar.style.left).toBe("221px");
    expect(toolbar.style.top).toBe("152px");
    expect(toolbar.style.transform).toBe("translateY(-100%)");

    renderToolbar(
      <VSelectionToolbar anchorRect={{ ...anchorRect, top: 20, bottom: 40 }} ariaLabel="Selection actions"><VButton>Quote</VButton></VSelectionToolbar>,
    );
    expect(toolbar.style.top).toBe("48px");
    expect(toolbar.style.transform).toBe("none");
  });

  it("remeasures on element and viewport resize and releases observers and listeners on unmount", () => {
    let width = 240;
    let viewportWidth = 1000;
    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => viewportWidth);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(800);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(() => ({
      left: 0, right: width, top: 0, bottom: 48, width, height: 48, x: 0, y: 0,
      toJSON: () => ({}),
    }));
    let notifyResize: ResizeObserverCallback | undefined;
    const observe = vi.fn();
    const disconnect = vi.fn();
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: ResizeObserverCallback) { notifyResize = callback; }
      observe = observe;
      disconnect = disconnect;
    });
    const added = vi.spyOn(window, "addEventListener");
    const removed = vi.spyOn(window, "removeEventListener");
    const toolbar = renderToolbar(
      <VSelectionToolbar anchorRect={anchorRect} ariaLabel="Selection actions"><VButton>Quote</VButton></VSelectionToolbar>,
    );
    expect(observe).toHaveBeenCalledWith(toolbar);
    expect(toolbar.style.left).toBe("205px");

    width = 300;
    act(() => notifyResize?.([], {} as ResizeObserver));
    expect(toolbar.style.left).toBe("175px");
    viewportWidth = 360;
    act(() => window.dispatchEvent(new Event("resize")));
    expect(toolbar.style.left).toBe("48px");
    const resizeListener = added.mock.calls.find(([event]) => event === "resize")?.[1];
    expect(resizeListener).toBeTypeOf("function");

    act(() => root?.unmount());
    root = null;
    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(removed).toHaveBeenCalledWith("resize", resizeListener);
    expect(document.querySelector('[data-vui="selection-toolbar"]')).toBeNull();
  });

  it("renders the same non-modal toolbar during server rendering without document", () => {
    vi.stubGlobal("document", undefined);
    try {
      const markup = renderToStaticMarkup(
        <VSelectionToolbar anchorRect={anchorRect} ariaLabel="Selection actions"><VButton>Quote</VButton></VSelectionToolbar>,
      );
      expect(markup).toContain('role="toolbar"');
      expect(markup).toContain('aria-label="Selection actions"');
      expect(markup).toContain("Quote");
      expect(markup).not.toContain("aria-modal");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
