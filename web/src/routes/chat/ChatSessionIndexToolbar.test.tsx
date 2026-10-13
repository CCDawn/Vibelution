// @vitest-environment happy-dom
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VuiProvider } from "../../components/vui";
import { ChatSessionIndexToolbar } from "./ChatSessionIndexToolbar";
import type { SessionListPreferences } from "./sessionListPreferences";

let root: Root;
let host: HTMLDivElement;
afterEach(async () => { if (root) await act(async () => root.unmount()); host?.remove(); });
function button(label: string) {
  const result = [...document.querySelectorAll<HTMLButtonElement>("button")].find(el => el.getAttribute("aria-label") === label || el.textContent?.trim() === label);
  if (!result) throw new Error(`Missing button: ${label}`);
  return result;
}
async function mount() {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const onSearch = vi.fn();
  const onCreate = vi.fn();
  function Harness() {
    const [archived, setArchived] = useState(false);
    const [preferences, setPreferences] = useState<SessionListPreferences>({sortBy:"updatedAt", timelineGrouping:false});
    const [createOpen, setCreateOpen] = useState(false);
    const [optionsOpen, setOptionsOpen] = useState(false);
    return <VuiProvider><ChatSessionIndexToolbar lang="zh" archived={archived} preferences={preferences}
      onPreferencesChange={patch => setPreferences(current => ({...current,...patch}))} onToggleArchive={() => setArchived(v => !v)}
      onSearch={onSearch} onCollapse={() => {}} createOpen={createOpen} onCreateOpenChange={setCreateOpen}
      optionsOpen={optionsOpen} onOptionsOpenChange={setOptionsOpen}
      createItems={[{id:"new-session",label:"新建会话",onSelect:onCreate}]} /></VuiProvider>;
  }
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<Harness />));
  return {onSearch,onCreate};
}
describe("approved single-row session toolbar", () => {
  it("keeps four visible actions and routes the creation menu and search", async () => {
    const {onSearch,onCreate} = await mount();
    expect(host.querySelectorAll("button")).toHaveLength(4);
    await act(async () => button("搜索会话、Agent 或团队").click());
    expect(onSearch).toHaveBeenCalledOnce();
    await act(async () => button("新建").dispatchEvent(new PointerEvent("pointerdown", {bubbles:true,button:0,ctrlKey:false})));
    await act(async () => document.querySelector<HTMLElement>('[role="menuitem"]')!.click());
    expect(onCreate).toHaveBeenCalledOnce();
  });
  it("keeps sort mutually exclusive, retains grouping through archive, and exposes a return", async () => {
    await mount();
    await act(async () => button("更多与显示选项").click());
    const created = document.querySelector<HTMLInputElement>('input[value="createdAt"]')!;
    await act(async () => created.click());
    expect(created.checked).toBe(true);
    expect(document.querySelector<HTMLInputElement>('input[value="updatedAt"]')?.checked).toBe(false);
    const grouping = document.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    await act(async () => grouping.click());
    expect(grouping.checked).toBe(true);
    await act(async () => button("查看已归档").click());
    expect(host.querySelector("h2")?.textContent).toBe("已归档");
    expect(document.querySelector('[data-vui="chat-session-display-options"]')).toBeNull();
    await act(async () => button("返回会话").click());
    await act(async () => button("更多与显示选项").click());
    expect(document.querySelector<HTMLInputElement>('input[value="createdAt"]')?.checked).toBe(true);
    expect(document.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
  });
});
