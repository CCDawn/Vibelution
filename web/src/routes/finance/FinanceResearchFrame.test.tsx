// @vitest-environment happy-dom
import React, { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceResearchFrame } from "./FinanceResearchFrame";
import { persistPaneVisibility } from "../../components/layout/paneVisibilityPersistence";

vi.mock("../../components/layout/paneVisibilityPersistence", () => ({
  readPaneVisibility: () => true, persistPaneVisibility: vi.fn(),
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let node: HTMLDivElement;
let resize: (width: number) => void;
let mounts = 0;
function Conversation() {
  useEffect(() => { mounts++; }, []);
  return <div data-finance-native-conversation><textarea aria-label="原生研究输入" defaultValue="保留草稿" /></div>;
}
beforeEach(() => {
  mounts = 0; vi.clearAllMocks();
  vi.stubGlobal("ResizeObserver", class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) {
      if (target.matches("section")) resize = width => this.callback([{ target, contentRect: { width } } as ResizeObserverEntry], this as unknown as ResizeObserver);
    }
    unobserve() {} disconnect() {}
  });
  node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
});
afterEach(() => { act(() => root.unmount()); node.remove(); vi.unstubAllGlobals(); });
function render(reveal = 0) {
  act(() => root.render(<FinanceResearchFrame zh aside={<Conversation />} conversationRevealKey={reveal} sidebar={close => <><button onClick={close}>关闭导航</button><nav><button>股票研究</button></nav></>}><p>研究正文</p></FinanceResearchFrame>));
}
function click(label: string) {
  const target = [...node.querySelectorAll<HTMLButtonElement>("button")].find(item => item.getAttribute("aria-label") === label || item.textContent === label);
  expect(target).toBeTruthy(); act(() => target!.click());
}
it("keeps one native conversation and its draft mounted through responsive collapse and reveal", () => {
  render(); const input = node.querySelector("textarea");
  act(() => resize(1280));
  expect(node.querySelector('[data-vui="split-aside"]')?.hasAttribute("hidden")).toBe(true);
  click("展开对话栏");
  expect(node.querySelector('[data-vui="split-aside"]')?.hasAttribute("hidden")).toBe(false);
  click("收起对话栏"); render(1);
  expect(node.querySelector("textarea")).toBe(input);
  expect(input?.value).toBe("保留草稿"); expect(mounts).toBe(1);
});
it("keeps compact visibility out of desktop preferences and returns from navigation with Escape", () => {
  render(); act(() => resize(390));
  click("展开功能栏");
  expect(node.querySelector('[data-vui="split-sidebar"]')?.hasAttribute("hidden")).toBe(false);
  act(() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  expect(node.querySelector('[data-vui="split-sidebar"]')?.hasAttribute("hidden")).toBe(true);
  click("展开功能栏"); click("股票研究");
  expect(node.querySelector('[data-vui="split-sidebar"]')?.hasAttribute("hidden")).toBe(true);
  expect(persistPaneVisibility).not.toHaveBeenCalled();
  act(() => resize(1920));
  expect(node.querySelector('[data-vui="split-sidebar"]')?.hasAttribute("hidden")).toBe(false);
  expect(node.querySelector('[data-vui="split-aside"]')?.hasAttribute("hidden")).toBe(false);
});
