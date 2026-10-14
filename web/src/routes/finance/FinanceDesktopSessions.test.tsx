// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionSummary } from "../../api/types";
import { FinanceDesktopSessions } from "./FinanceDesktopSessions";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const row = (id: string): SessionSummary => ({ id, agentId: "finance", title: `研究 ${id}`, status: "idle", taskSummary: "", lastActive: "", updatedAt: "", currentPhase: "" });
const a = row("a"), b = row("old-search-result");
let container: HTMLDivElement, root: Root;
const onOpen = vi.fn(), onAction = vi.fn();
beforeEach(() => { vi.clearAllMocks(); container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
async function render(active: SessionSummary, removedIds: string[] = []) {
  await act(async () => root.render(<FinanceDesktopSessions activeId={active.id} activeSession={active} sessions={[a]} removedIds={removedIds} zh creating={false} pending={false} onOpen={onOpen} onAction={onAction} onNew={() => {}} onManage={() => {}} />));
}
describe("finance desktop session tabs", () => {
  it("keeps a verified old search result open after returning to a recent session", async () => {
    await render(a); await render(b); await render(a);
    expect([...container.querySelectorAll('[role="tab"]')].map(tab => tab.textContent)).toEqual([a.title, b.title]);
  });
  it("closes a tab by selecting its neighbor without deleting or archiving", async () => {
    await render(a); await render(b);
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="关闭当前标签"]')!.click());
    expect(onOpen).toHaveBeenCalledWith(a);
    expect(onAction).not.toHaveBeenCalled();
    await render(a);
    expect([...container.querySelectorAll('[role="tab"]')].map(tab => tab.textContent)).toEqual([a.title]);
  });
  it("removes a cached tab only after a confirmed lifecycle change", async () => {
    await render(a); await render(b); await render(a, [b.id]);
    expect(container.textContent).not.toContain(b.title);
    expect(onAction).not.toHaveBeenCalled();
  });
  it("keeps the last tab rather than navigating to auto-create a new session", async () => {
    await render(a);
    expect(container.querySelector<HTMLButtonElement>('button[aria-label="关闭当前标签"]')?.disabled).toBe(true);
    expect(onOpen).not.toHaveBeenCalled();
    expect(onAction).not.toHaveBeenCalled();
  });
});
