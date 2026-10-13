// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/vui", () => ({ VNativeButton: (props: React.ComponentProps<"button">) => <button {...props}/> }));
vi.mock("./AgentDetailHeaderPanel", () => ({AgentDetailHeaderPanel: () => null}));
vi.mock("./AgentFocusedOverviewPanel", () => ({AgentFocusedOverviewPanel: () => null}));
vi.mock("./shared/ProgressiveRegionSkeleton", () => ({ProgressiveRegionSkeleton: () => null}));
vi.mock("./finance/FinancialAssistantStatusNote", () => ({FinancialAssistantStatusNote: () => null}));
vi.mock("./AgentConfigPrimaryPanePanel", () => ({AgentConfigPrimaryPanePanel: ({section}:{section:string}) => <output data-section={section}>{section}</output>}));
vi.mock("./AgentConfigPolicyPanePanel", () => ({AgentConfigPolicyPanePanel: () => <output data-section="capability"/>}));
vi.mock("./AgentRuntimePolicyPanel", () => ({AgentRuntimePolicyPanel: () => <output data-section="runtime"/>}));

import { AgentSelectedDetailContentPanel, type AgentSelectedDetailContentPanelProps } from "./AgentSelectedDetailContentPanel";
(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | null = null;
let host: HTMLDivElement | null = null;
async function render(agentId="a", agentName="A", preferOpsSection=false) {
  if (!host) {host=document.createElement("div");document.body.append(host);root=createRoot(host);}
  const props = {activePane:"config",agentId,header:{lang:"zh",agentName},configPrimary:{personaProfile:{},taskProfile:{},healthMaintenance:{health:{hasIssues:false}}},configPolicies:{},activity:{runtimePolicy:{}},preferOpsSection} as AgentSelectedDetailContentPanelProps;
  await act(async()=>{root?.render(<AgentSelectedDetailContentPanel {...props}/>);await vi.dynamicImportSettled();});
}
afterEach(()=>{act(()=>root?.unmount());host?.remove();root=null;host=null;});
describe("Agent configuration navigation",()=>{
  it("opens models by default and exposes each editable group directly",async()=>{
    await render();
    expect(host?.querySelector('[data-section="models"]')).not.toBeNull();
    expect(Array.from(host!.querySelectorAll('nav button')).map(e=>e.textContent)).toEqual(["模型","基本","人物","任务","工具与记忆","委派与监督","运维"]);
    for(const [name,section] of [["基本","basic"],["人物","persona"],["任务","task"],["工具与记忆","capability"],["委派与监督","runtime"]]){
      await act(async()=>{Array.from(host!.querySelectorAll<HTMLButtonElement>('nav button')).find(e=>e.textContent===name)?.click();await vi.dynamicImportSettled();});
      expect(host?.querySelector(`[data-section="${section}"]`)).not.toBeNull();
    }
  });
  it("keeps the selected group after a name save, and resets for another Agent",async()=>{
    await render();
    await act(async()=>{Array.from(host!.querySelectorAll<HTMLButtonElement>('nav button')).find(e=>e.textContent==="人物")?.click();await vi.dynamicImportSettled();});
    await render("a","Renamed A");
    expect(host?.querySelector('[data-section="persona"]')).not.toBeNull();
    await render("b","B");
    expect(host?.querySelector('[data-section="models"]')).not.toBeNull();
  });
});
