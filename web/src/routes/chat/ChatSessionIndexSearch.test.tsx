// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentInstance, SessionSummary, Team } from "../../api/types";
import { VuiProvider } from "../../components/vui";
import { ChatSessionIndexSearch, type ChatSessionIndexSearchProps } from "./ChatSessionIndexSearch";
import { clearSessionDeleteTombstone, markSessionDeleteTombstone } from "../sessionDeleteTombstone";

const queryMock = vi.hoisted(() => vi.fn());
vi.mock("../useSessionSearchQuery", () => ({ useSessionSearchQuery: queryMock }));
let root: Root;
let host: HTMLDivElement;
const agent = {agentId:"a",agentCode:"DEV",displayName:"开发 Agent",kind:"persistent",status:"ready",metadata:{}} as AgentInstance;
const team = {teamId:"t",name:"研究团队"} as Team;
const session = {id:"s",title:"接口梳理",agentId:"a",status:"ready",workspacePath:"C:/research/workspace",lastActive:"2026-10-13"} as SessionSummary;
beforeEach(() => queryMock.mockReturnValue({sessions:[session],isLoading:false,isFetching:false,totalEstimate:1,
  hasMore:false,isLoadingMore:false,debouncedQueryText:"",searchError:undefined,retrySearch:vi.fn(),loadMore:vi.fn()}));
afterEach(async () => { if(root) await act(async () => root.unmount()); host?.remove(); clearSessionDeleteTombstone("s"); });
async function mount(patch: Partial<ChatSessionIndexSearchProps> = {}) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT=true;
  const props: ChatSessionIndexSearchProps = {open:true,onOpenChange:vi.fn(),lang:"zh",agentsById:new Map([["a",agent]]),
    teams:[team],knownSessions:new Map([["s",session]]),activeSessionId:null,approvalSessionIds:[],runningSessionIds:[],
    onOpenSession:vi.fn(),onOpenAgent:vi.fn(),onOpenTeam:vi.fn(),...patch};
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
  await act(async () => root.render(<VuiProvider><ChatSessionIndexSearch {...props} /></VuiProvider>));
  return props;
}
function scope(label: string) { return [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(el=>el.textContent===label)!; }
async function selectScope(label: string) { await act(async () => scope(label).dispatchEvent(new MouseEvent("mousedown", {bubbles:true,button:0,ctrlKey:false}))); }
function result(title: string) { return [...document.querySelectorAll<HTMLButtonElement>('button[data-index]')].find(el=>el.textContent?.includes(title))!; }
async function search(text: string) {
  const input=document.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(input,text);
    input.dispatchEvent(new Event("input",{bubbles:true})); });
}
describe("unified chat index search", () => {
  it("shows paged session hits alongside eligible Agent and team navigation", async () => {
    const props=await mount();
    expect(document.querySelectorAll('button[data-index]')).toHaveLength(3);
    await act(async () => result("接口梳理").click());
    expect(props.onOpenSession).toHaveBeenCalledWith("s");
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });
  it("uses directory-only scopes without sending session queries and opens the correct owner", async () => {
    const props=await mount();
    await selectScope("Agent");
    expect(queryMock.mock.lastCall?.[0].enabled).toBe(false);
    expect(document.querySelectorAll('button[data-index]')).toHaveLength(1);
    await act(async () => result("开发 Agent").click());
    expect(props.onOpenAgent).toHaveBeenCalledWith(agent);
    await selectScope("团队");
    await act(async () => result("研究团队").click());
    expect(props.onOpenTeam).toHaveBeenCalledWith(team);
  });
  it("preserves loaded workspace matches and does not resurrect deleted sessions", async () => {
    queryMock.mockReturnValue({...queryMock(),sessions:[],totalEstimate:0});
    await mount();
    await search("workspace");
    expect(result("接口梳理")).toBeDefined();
    markSessionDeleteTombstone("s");
    await search("research");
    expect(document.querySelectorAll('button[data-index]')).toHaveLength(0);
  });
  it("excludes archived and Companion identities from ordinary Agent results", async () => {
    await mount({agentsById:new Map([["a",agent],["archived",{...agent,agentId:"archived",status:"archived"}],
      ["companion",{...agent,agentId:"companion",metadata:{virtualHumanCompanion:true}}]])});
    await selectScope("Agent");
    expect(document.querySelectorAll('button[data-index]')).toHaveLength(1);
  });
});
