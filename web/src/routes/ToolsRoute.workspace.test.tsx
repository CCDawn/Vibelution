/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentInstance, ToolBundle, ToolRegistryItem, ToolRegistryPayload } from "../api/types";
import { queryKeys } from "../api/queryKeys";

vi.mock("../i18n/useAppI18n", () => ({useAppI18n: () => ({lang:"zh", t:(key:string)=>key})}));
vi.mock("../i18n/useShellI18n", () => ({useShellI18n: () => ({lang:"zh", t:(key:string)=>key})}));
vi.mock("../api/tools", () => ({fetchToolRegistry:vi.fn(),fetchToolImage2Models:vi.fn(),fetchWebSearchToolHealth:vi.fn(),bulkDeleteToolRegistry:vi.fn(),bulkSetGeneratedToolsEnabled:vi.fn(),deleteTool:vi.fn(),setGeneratedToolEnabled:vi.fn(),setToolImage2DefaultModel:vi.fn(),testTool:vi.fn()}));
vi.mock("../api/agents", () => ({listAgentSummaries:vi.fn(),updateAgentToolPolicy:vi.fn(),validateAgentToolPolicy:vi.fn()}));
import { updateAgentToolPolicy, validateAgentToolPolicy } from "../api/agents";
import { ToolsRoute } from "./ToolsRoute";

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
let root:Root; let host:HTMLDivElement; let client:QueryClient;
const scope={visible:true,callable:true,llmVisible:true,runtimeActive:true,testable:false,blockReason:""};
function tool(name:string):ToolRegistryItem {
  return {id:name,name,description:"Description for "+name,source:"built_in",category:"memory",categoryLabel:"记忆与上下文",bundleIds:[],capabilityTags:["technical_long_tag"],riskTags:[],permissionTier:"high",status:"active",enabled:true,validated:true,llmVisible:true,runtimeActive:true,deleteAllowed:false,blockReason:"protected",validationError:"",argsSchema:{},testPolicy:{mode:"blocked",callable:false,runtimeCall:false,simulated:false,reason:"protected",argsPreview:{}},agentScopes:{main_agent:scope},createdAt:"",updatedAt:""};
}
function bundle(id:string,names:string[]):ToolBundle {
  return {bundleId:id,label:id,description:"Package "+id,category:"memory",toolNames:names,preferredToolNames:[],toolCount:names.length,preferredToolCount:0,highRiskToolCount:names.length,explicitAllowToolCount:0,riskTags:[]};
}
async function mount(query="view=policy") {
  const rows=[tool("shared_tool"),tool("alpha_tool"),tool("beta_tool"),tool("loose_tool")];
  const payload:ToolRegistryPayload={schemaVersion:1,mode:"runtime",storagePath:"fixture",counts:{total:4,builtIn:4,generated:0,llmVisible:4,runtimeActive:4,enabledGenerated:0,invalidGenerated:0},agentScopes:[],toolBundles:[bundle("Alpha",["shared_tool","alpha_tool"]),bundle("Beta",["shared_tool","beta_tool"]),bundle("Empty",[])],tools:rows};
  const agent={agentId:"agent-a",agentCode:"A1",displayName:"Fixture Agent",status:"idle",toolPolicy:{policyId:"fixture",allowedTools:["alpha_tool"],preferredTools:[],blockedTools:[],readScopes:["private"],writeScopes:["private"]}} as AgentInstance;
  client=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:Infinity,staleTime:Infinity}}});
  client.setQueryData(queryKeys.tools(),payload);client.setQueryData(queryKeys.agents(),[agent]);
  client.setQueryData(queryKeys.toolImage2Models(),{selectedModel:{modelRef:"",discoveredModels:[]},models:[]});
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
  await act(async()=>{root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/agents/tools?"+query]}><ToolsRoute/></MemoryRouter></QueryClientProvider>);});
}
async function click(element:HTMLElement|null){expect(element).not.toBeNull();await act(async()=>{element!.dispatchEvent(new MouseEvent("mousedown",{button:0,bubbles:true}));element!.click();});}
function button(text:string){return [...host.querySelectorAll<HTMLButtonElement>("button")].find(e=>e.textContent?.trim()===text) ?? null;}
function viewTab(text:string){return [...host.querySelectorAll<HTMLElement>('[role="tab"]')].find(e=>e.textContent===text) ?? null;}
afterEach(async()=>{await act(async()=>root?.unmount());host?.remove();client?.clear();vi.clearAllMocks();});

describe("Tools workspaces retain policy semantics",()=>{
  it("keeps unsaved permissions and shared-package tools across view switches",async()=>{
    await mount("focus=bundle&bundle=Alpha&agent=A1");
    expect(host.querySelector('[data-tools-view="policy"]')).not.toBeNull();
    await click(button("Beta2"));
    let policy=host.querySelector('[data-tools-view="policy"]')!;
    expect(policy.textContent).toContain("shared_tool");expect(policy.textContent).toContain("beta_tool");
    const tabs=policy.querySelector('[aria-label="beta_tool"]')!;
    await click([...tabs.querySelectorAll<HTMLElement>('[role="tab"]')].find(e=>e.textContent==="允许")!);
    expect(host.querySelector(".workspaceState")?.textContent ?? host.textContent).toContain("未保存");
    await click(viewTab("工具库"));expect(host.querySelector('[data-tools-view="policy"]')).toBeNull();
    await click(viewTab("Agent 工具配置"));
    policy=host.querySelector('[data-tools-view="policy"]')!;
    expect(policy.querySelector('[aria-label="beta_tool"] [data-state="active"]')?.textContent).toBe("允许");
    expect(host.querySelector("footer")?.textContent).toContain("草稿有变更");
    expect(updateAgentToolPolicy).not.toHaveBeenCalled();expect(validateAgentToolPolicy).not.toHaveBeenCalled();
  });
  it("supports unbundled and empty packages without falling back to another package",async()=>{
    await mount();await click(button("未归入工具包1"));
    let policy=host.querySelector('[data-tools-view="policy"]')!;expect(policy.textContent).toContain("loose_tool");expect(policy.textContent).not.toContain("beta_tool");
    expect(host.textContent).not.toContain("未找到深链指定的工具包");
    await click(button("Empty0"));policy=host.querySelector('[data-tools-view="policy"]')!;
    expect(policy.textContent).toContain("当前没有可分配工具");expect(policy.textContent).not.toContain("alpha_tool");
  });
  it("keeps source/risk/category in one caption and preserves counts while searching",async()=>{
    await mount();const row=host.querySelector(".toolPermissionRow")!;const metadata=row.querySelector(".toolPermissionMeta")!;
    expect(metadata.textContent).toContain("内置");expect(metadata.textContent).toContain("高风险");expect(metadata.textContent).toContain("记忆与上下文");
    expect(row.querySelector('button[aria-label*="工具标签"]')).not.toBeNull();
    const countBefore=host.querySelector('[data-tools-role="policy-summary"]')!.textContent;
    const input=host.querySelector<HTMLInputElement>('input[placeholder="搜索可分配工具"]')!;
    await act(async()=>{const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!;setter.call(input,"beta_tool");input.dispatchEvent(new Event("input",{bubbles:true}));});
    expect(host.querySelector('[data-tools-role="policy-summary"]')!.textContent).toBe(countBefore);
    expect(host.querySelector("footer")?.parentElement?.className).toContain("agentPermissionSummaryPanel");
    expect(host.querySelector('[data-tools-role="policy-scroll"]')!.contains(host.querySelector("footer"))).toBe(false);
  });
});
