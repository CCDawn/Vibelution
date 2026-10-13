// @vitest-environment happy-dom
import React, { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GlobalCommandSurfaces } from "./GlobalCommandSurfaces";
import { SESSION_INDEX_SEARCH_EVENT } from "../shortcuts/sessionSearchDispatch";
import { writeStoredShortcutOverrides } from "../shortcuts/shortcutOverrides";

vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({data:{}}) }));
vi.mock("react-router-dom", () => ({ useNavigate: () => () => {} }));
vi.mock("../i18n/useShellI18n", () => ({useShellI18n: () => ({lang:"zh", t:(key:string)=>key})}));
vi.mock("../routes/useSessionSearchQuery", () => ({useSessionSearchQuery: () => ({sessions:[],isLoading:false,
  hasMore:false,isLoadingMore:false,isFetching:false,debouncedQueryText:"",retrySearch:()=>{},loadMore:()=>{}})}));
let root: Root;
let host: HTMLDivElement;
beforeEach(() => { localStorage.clear(); writeStoredShortcutOverrides({}); });
afterEach(async () => {if(root)await act(async () => root.unmount());host?.remove();localStorage.clear();});
function ChatSearchHarness() {
  const [opens,setOpens]=useState(0);
  useEffect(()=>{const handle=(event:Event)=>{event.preventDefault();setOpens(n=>n+1);};
    window.addEventListener(SESSION_INDEX_SEARCH_EVENT,handle);return()=>window.removeEventListener(SESSION_INDEX_SEARCH_EVENT,handle);},[]);
  return <div data-testid="chat-search">{opens}</div>;
}
async function mount(chat: boolean) {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
  await act(async()=>root.render(<><GlobalCommandSurfaces />{chat?<ChatSearchHarness />:null}</>));
}
async function key(letter:string) {await act(async()=>window.dispatchEvent(new KeyboardEvent("keydown",{
  key:letter,code:`Key${letter.toUpperCase()}`,ctrlKey:true,bubbles:true,cancelable:true})));}
describe("global shortcut handoff to mounted Chat search",()=>{
  it("routes default Ctrl+K and session-search Ctrl+P to one Chat surface",async()=>{
    await mount(true);await key("k");await key("p");
    expect(host.querySelector('[data-testid="chat-search"]')?.textContent).toBe("2");
    expect(document.querySelector('[data-vui="global-command-palette"]')).toBeNull();
    expect(document.querySelector('[data-vui="global-session-search"]')).toBeNull();
  });
  it("retains the command palette outside Chat",async()=>{
    await mount(false);await key("k");
    expect(document.querySelector('input[aria-label="搜索命令或导航…"]')).not.toBeNull();
  });
  it("honors custom palette bindings while delegating remapped session search",async()=>{
    writeStoredShortcutOverrides({openCommandPalette:["CmdOrCtrl+j"],openSessionSearch:["CmdOrCtrl+x"]});
    await mount(true);await key("k");
    expect(host.querySelector('[data-testid="chat-search"]')?.textContent).toBe("0");
    await key("j");expect(document.querySelector('input[aria-label="搜索命令或导航…"]')).not.toBeNull();
    await key("x");expect(host.querySelector('[data-testid="chat-search"]')?.textContent).toBe("1");
  });
});
