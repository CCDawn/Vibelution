// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionSummary } from "../../api/types";
import { FinanceWorkspaceSidebar } from "./FinanceWorkspaceSidebar";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
afterEach(async () => { await act(async () => root?.unmount()); root = undefined; document.body.replaceChildren(); });
const rows = [
  { id: "ready", agentId: "finance", title: "已完成的研究", status: "ready", updatedAt: "2026-10-10T10:00:00Z" },
  { id: "running", agentId: "finance", title: "运行中的研究", status: "running", updatedAt: "2026-10-10T11:00:00Z" },
] as SessionSummary[];
async function render(overrides: Partial<React.ComponentProps<typeof FinanceWorkspaceSidebar>> = {}) {
  const node = document.createElement("div"); document.body.appendChild(node); root ??= createRoot(node);
  const props = { records: rows, selectedId: "ready", zh: true, area: "workspace", collection: "recent" as const, onCollectionChange: vi.fn(), search: "", onSearchChange: vi.fn(), loading: false, error: false, hasMore: false, morePending: false, onRetry: vi.fn(), onMore: vi.fn(), creating: false, onNewResearch: vi.fn(), configHref: "/agents", onNavigate: vi.fn(), onOpen: vi.fn(), onAction: vi.fn(), actionPending: false, onBatchAction: vi.fn(), onCollapse: vi.fn(), ...overrides };
  await act(async () => root!.render(<MemoryRouter><FinanceWorkspaceSidebar {...props} /></MemoryRouter>));
  return { node, props };
}
async function click(node: HTMLElement, name: string) {
  const button = Array.from(node.querySelectorAll<HTMLButtonElement>("button")).find(e => e.getAttribute("aria-label") === name || e.textContent === name)!;
  expect(button).toBeTruthy(); await act(async () => button.click());
}
describe("desktop finance sidebar management", () => {
  it("keeps native row actions and adds a direct current-session delete", async () => {
    const { node, props } = await render();
    await click(node, "删除当前研究"); expect(props.onAction).toHaveBeenCalledWith(rows[0], "delete");
    await click(node, "收起会话栏"); expect(props.onCollapse).toHaveBeenCalled();
    expect(node.querySelectorAll('button[aria-label^="管理研究："]')).toHaveLength(2);
  });
  it("hides row menus in management, selects the displayed rows, and sends one batch", async () => {
    const { node, props } = await render();
    await click(node, "管理");
    expect(node.querySelectorAll('button[aria-label^="管理研究："]')).toHaveLength(0);
    expect(node.querySelector('[aria-label="删除当前研究"]')).toBeNull();
    await act(async () => node.querySelector<HTMLInputElement>('input[aria-label="全选当前列表"]')!.click());
    await click(node, "归档所选研究"); expect(props.onBatchAction).toHaveBeenCalledWith(rows, "archive");
    await click(node, "删除所选研究"); expect(props.onBatchAction).toHaveBeenLastCalledWith(rows, "delete", expect.anything());
  });
  it("disables direct deletion of running research", async () => {
    const { node, props } = await render({ selectedId: "running" });
    expect(node.querySelector<HTMLButtonElement>('[aria-label="删除当前研究"]')?.disabled).toBe(true);
    await click(node, "删除当前研究"); expect(props.onAction).not.toHaveBeenCalled();
  });
});
