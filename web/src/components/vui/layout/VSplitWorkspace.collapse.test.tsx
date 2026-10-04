/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VSplitWorkspace, type VSplitWorkspaceResizeConfig } from "./VSplitWorkspace";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
const labels = { separatorLabel: "调整设置导航", collapseLabel: "收起设置导航", expandLabel: "展开设置导航" };
const input = <input aria-label="未保存草稿" defaultValue="初始草稿" />;
async function render(collapse: VSplitWorkspaceResizeConfig["collapse"]) {
  await act(() => root.render(<VSplitWorkspace resize={{ layoutId: "config-settings", collapse }} sidebar={input} main={<div>Models</div>} aside={<div>Inspector</div>} />));
}
const pane = () => host.querySelector<HTMLElement>('[data-vui="split-sidebar"]')!;
const button = (name: string) => host.querySelector<HTMLButtonElement>(`button[aria-label="${name}"]`)!;

beforeEach(() => { host = document.createElement("div"); document.body.append(host); root = createRoot(host); window.localStorage.clear(); });
afterEach(async () => { await act(() => root.unmount()); host.remove(); });

describe("VSplitWorkspace controlled collapse", () => {
  it("requests changes from the owner and preserves mounted drafts and widths", async () => {
    const onCollapsedChange = vi.fn();
    await render({ sidebar: { ...labels, collapsed: true, onCollapsedChange } });
    const draft = host.querySelector<HTMLInputElement>("input")!;
    draft.value = "正在编辑的草稿";
    const width = pane().style.width;
    expect(pane().hidden).toBe(true);
    await act(() => button(labels.expandLabel).click());
    expect(onCollapsedChange).toHaveBeenCalledWith(false);
    expect(pane().hidden).toBe(true);
    await render({ sidebar: { ...labels, collapsed: false, onCollapsedChange } });
    expect(pane().hidden).toBe(false);
    expect(host.querySelector("input")).toBe(draft);
    expect(draft.value).toBe("正在编辑的草稿");
    expect(pane().style.width).toBe(width);
    await act(() => button(labels.collapseLabel).click());
    expect(onCollapsedChange).toHaveBeenLastCalledWith(true);
  });

  it("keeps the existing uncontrolled toggle when no controlled value is supplied", async () => {
    await render({ sidebar: labels });
    expect(pane().hidden).toBe(false);
    await act(() => button(labels.collapseLabel).click());
    expect(pane().hidden).toBe(true);
    await act(() => button(labels.expandLabel).click());
    expect(pane().hidden).toBe(false);
  });

  it("controls the aside independently without changing the sidebar", async () => {
    const onCollapsedChange = vi.fn();
    await render({ sidebar: labels, aside: { ...labels, expandLabel: "展开详情", collapsed: true, onCollapsedChange } });
    expect(pane().hidden).toBe(false);
    expect(host.querySelector<HTMLElement>('[data-vui="split-aside"]')!.hidden).toBe(true);
    await act(() => button("展开详情").click());
    expect(onCollapsedChange).toHaveBeenCalledWith(false);
    expect(pane().hidden).toBe(false);
    expect(host.querySelector<HTMLElement>('[data-vui="split-aside"]')!.hidden).toBe(true);
  });

  it.each(["sidebar", "aside"] as const)("retains the last accepted %s state when control is removed", async (side) => {
    const onCollapsedChange = vi.fn();
    const targetPane = () => host.querySelector<HTMLElement>(`[data-vui="split-${side}"]`)!;
    await render({ [side]: { ...labels, collapsed: true, onCollapsedChange } });
    await render({ [side]: labels });
    expect(targetPane().hidden).toBe(true);
    await act(() => button(labels.expandLabel).click());
    expect(targetPane().hidden).toBe(false);
    await act(() => button(labels.collapseLabel).click());
    expect(targetPane().hidden).toBe(true);
    await render({ [side]: { ...labels, collapsed: false, onCollapsedChange } });
    await render({ [side]: labels });
    expect(targetPane().hidden).toBe(false);
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });
});
