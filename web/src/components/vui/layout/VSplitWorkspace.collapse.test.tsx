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
async function renderSinglePane(
  collapse: NonNullable<VSplitWorkspaceResizeConfig["collapse"]>,
  side: "sidebar" | "aside",
) {
  await act(() => root.render(
    <VSplitWorkspace
      resize={{ layoutId: "config-settings", collapse }}
      sidebar={side === "sidebar" ? input : undefined}
      main={<div>Models</div>}
      aside={side === "aside" ? <div>Inspector</div> : undefined}
    />,
  ));
}
const pane = () => host.querySelector<HTMLElement>('[data-vui="split-sidebar"]')!;
const sidePane = (side: "sidebar" | "aside") => host.querySelector<HTMLElement>(`[data-vui="split-${side}"]`)!;
const mainPane = () => host.querySelector<HTMLElement>('[data-vui="split-main"]')!;
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
    expect(host.querySelector('[data-vui-layout-handle="collapse-resize"]')).not.toBeNull();
    expect(host.querySelector('[data-vui-layout-handle="resize"][aria-label="调整左侧栏宽度"]')).toBeNull();
    await act(() => button(labels.collapseLabel).click());
    expect(pane().hidden).toBe(true);
    expect(host.querySelector('[data-vui-layout-handle="collapse-resize"]')).not.toBeNull();
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

  it("uses the header placement resize handle and restores the controlled sidebar width", async () => {
    const onCollapsedChange = vi.fn();
    const renderHeaderSidebar = (collapsed: boolean) => renderSinglePane({
      sidebar: { ...labels, placement: "header", collapsed, onCollapsedChange },
    }, "sidebar");

    await renderHeaderSidebar(false);
    expect(pane().hidden).toBe(false);
    const resizeHandle = host.querySelector<HTMLElement>('[data-vui-layout-handle="resize"]')!;
    expect(resizeHandle.getAttribute("aria-label")).toBe(labels.separatorLabel);
    expect(host.querySelector('[data-vui-layout-handle="collapse-resize"]')).toBeNull();
    expect(host.querySelector("button")).toBeNull();
    expect(host.querySelectorAll('[role="separator"]')).toHaveLength(1);

    await act(() => {
      resizeHandle.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
      return Promise.resolve();
    });
    expect(resizeHandle.getAttribute("aria-valuenow")).toBe("344");
    expect(JSON.parse(window.localStorage.getItem("vibelution.pane-layouts.v1") ?? "{}"))
      .toMatchObject({ "config-settings": { sidebar: 344 } });

    await renderHeaderSidebar(true);
    expect(pane().hidden).toBe(true);
    expect(host.querySelector('[data-vui-layout-handle]')).toBeNull();
    expect(host.querySelector("button")).toBeNull();
    expect(host.querySelectorAll('[role="separator"]')).toHaveLength(0);
    expect(mainPane().hidden).toBe(false);
    expect(mainPane().className).toContain("flex-1");

    await renderHeaderSidebar(false);
    expect(pane().hidden).toBe(false);
    expect(host.querySelector<HTMLElement>('[data-vui-layout-handle="resize"]')?.getAttribute("aria-valuenow"))
      .toBe("344");
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });

  it("supports header placement for the aside and removes its track while collapsed", async () => {
    const onCollapsedChange = vi.fn();
    const renderHeaderAside = (collapsed: boolean) => renderSinglePane({
      aside: { ...labels, placement: "header", collapsed, onCollapsedChange },
    }, "aside");

    await renderHeaderAside(false);
    expect(sidePane("aside").hidden).toBe(false);
    const resizeHandle = host.querySelector<HTMLElement>('[data-vui-layout-handle="resize"]')!;
    expect(resizeHandle.getAttribute("aria-label")).toBe(labels.separatorLabel);
    await act(() => {
      resizeHandle.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
      return Promise.resolve();
    });
    expect(resizeHandle.getAttribute("aria-valuenow")).toBe("344");

    await renderHeaderAside(true);
    expect(sidePane("aside").hidden).toBe(true);
    expect(host.querySelector('[data-vui-layout-handle]')).toBeNull();
    expect(host.querySelector("button")).toBeNull();
    expect(host.querySelectorAll('[role="separator"]')).toHaveLength(0);
    expect(mainPane().hidden).toBe(false);
    expect(mainPane().className).toContain("flex-1");

    await renderHeaderAside(false);
    expect(sidePane("aside").hidden).toBe(false);
    expect(host.querySelector<HTMLElement>('[data-vui-layout-handle="resize"]')?.getAttribute("aria-valuenow"))
      .toBe("344");
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });
});
