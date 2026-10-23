/** @vitest-environment happy-dom */
import React, { act, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { teamFlowKeys } from "../../../api/genericTeamWorkflows";
import { WorkflowWorkspaceLoading } from "./WorkflowWorkspaceLoading";
import { WorkflowLoadingBoundary } from "./WorkflowLoadingBoundary";
import { useWorkflowDefinitions } from "./useWorkflowDefinitions";
import { createWorkflow } from "./workflowTemplates";
import type { Flow } from "./workflowModel";

const api = vi.hoisted(() => ({ flows: vi.fn() }));
vi.mock("../../../api/genericTeamWorkflows", async original => ({ ...await original<typeof import("../../../api/genericTeamWorkflows")>(), listTeamFlows: api.flows }));
vi.mock("../useTeamsCatalogQueries", () => ({ useTeamsCatalogQueries: () => ({ requestedVisibleTeamId: "team-a", visibleTeams: [{teamId:"team-a",name:"A"}] }) }));
Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { localStorage.clear(); vi.clearAllMocks(); });
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });
function fixture() {
  const flow = createWorkflow("验收流程", "blank", []);
  flow.steps.splice(1, 0, ...Array.from({length: 4}, (_, i) => ({id:`extra-${i}`,kind:"agent" as const,label:`协作${i}`,owner:"",instruction:"处理"})));
  flow.fields = ["paragraph", "select", "text"].map((kind, i) => ({id:`field-${i}`,label:`输入${i}`,kind:kind as Flow["fields"][number]["kind"],required:true,options:kind === "select" ? ["公开"] : []}));
  return flow;
}
function markup(queryClient: QueryClient, teamId = "team-a") {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<QueryClientProvider client={queryClient}><WorkflowWorkspaceLoading teamId={teamId}/></QueryClientProvider>);
  return host;
}
it("uses this response's actual node and field structure, with no browser history", () => {
  const flow = fixture(), queryClient = client();
  queryClient.setQueryData(teamFlowKeys.flows("team-a"), {schemaVersion:1,teamId:"team-a",flows:[flow]});
  const host = markup(queryClient);
  expect(host.querySelectorAll("[data-team-flow-editor] li > button")).toHaveLength(flow.steps.length);
  expect(host.querySelectorAll('[data-team-inspector-body] [aria-label$="类型"]')).toHaveLength(3);
  expect(host.querySelector('[aria-label="输入2选项"]')).not.toBeNull();
  expect(host.querySelector('[data-team-inspector-footer]')).not.toBeNull();
  expect(host.querySelector("main[inert]")).not.toBeNull();
  expect(host.querySelector('[data-vui-layout-id="teams"]')).not.toBeNull();
  expect(localStorage.getItem("vibelution.team-flow-loading-shapes.v1")).toBeNull();
  queryClient.clear();
});
it("ignores old browser hints and reserves only known geometry until the request completes", () => {
  localStorage.setItem("vibelution.team-flow-loading-shapes.v1", JSON.stringify({"team-a":{at:Date.now(),flows:[{steps:["input","output"],fields:[]}]}}));
  const queryClient = client(), host = markup(queryClient);
  expect(host.querySelector('[data-vui="canvas-workbench-inspector"]')).not.toBeNull();
  expect(host.querySelector("[data-team-flow-editor]")).not.toBeNull();
  expect(host.querySelectorAll("[data-team-flow-editor] li > button")).toHaveLength(0);
  expect(host.querySelector('[aria-label="步骤名称"]')).not.toBeNull();
  expect(host.textContent).toContain("正在读取流程结构");
  expect(host.querySelector("[data-team-workspace-start]")).toBeNull();
  queryClient.clear();
});
it("honors an empty current response and never borrows another team's structure", () => {
  const queryClient = client();
  queryClient.setQueryData(teamFlowKeys.flows("team-a"), {schemaVersion:1,teamId:"team-a",flows:[]});
  expect(markup(queryClient).querySelector("[data-team-workspace-start]")).not.toBeNull();
  queryClient.setQueryData(teamFlowKeys.flows("team-b"), {schemaVersion:1,teamId:"team-b",flows:[fixture()]});
  expect(markup(queryClient).querySelector("[data-team-flow-editor]")).toBeNull();
  queryClient.clear();
});
it("keeps one cold request alive across the lazy-route handoff", async () => {
  const queryClient = client(), host = document.createElement("div"), root = createRoot(host);
  let resolveFlow!: (value: {schemaVersion:number;teamId:string;flows:Flow[]}) => void;
  let requestSignal: AbortSignal | undefined;
  api.flows.mockImplementation((_id, signal) => { requestSignal = signal; return new Promise(resolve => { resolveFlow = resolve; }); });
  let resolveChunk!: (value: {default: () => React.ReactNode}) => void;
  const Page = lazy(() => new Promise<{default: () => React.ReactNode}>(resolve => { resolveChunk = resolve; }));
  function Loaded() { const data = useWorkflowDefinitions("team-a"); return data.data ? <span data-ready>{data.data.flows[0].steps.length}</span> : <WorkflowWorkspaceLoading teamId="team-a"/>; }
  try {
    await act(async () => root.render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={["/teams?team=team-a&teamWorkspace=flows"]}><WorkflowLoadingBoundary><Suspense fallback={<WorkflowWorkspaceLoading/>}><Page/></Suspense></WorkflowLoadingBoundary></MemoryRouter></QueryClientProvider>));
    expect(api.flows).toHaveBeenCalledTimes(1);
    await act(async () => resolveChunk({default:Loaded}));
    expect(requestSignal?.aborted).toBe(false);
    const flow = fixture();
    await act(async () => { resolveFlow({schemaVersion:1,teamId:"team-a",flows:[flow]}); await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(api.flows).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[data-ready]")?.textContent).toBe(String(flow.steps.length));
  } finally { act(() => root.unmount()); queryClient.clear(); }
});
