/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Flow } from "./workflowModel";
import { useWorkflowWorkspace } from "./useWorkflowWorkspace";
import { createWorkflow } from "./workflowTemplates";
import { teamFlowKeys } from "../../../api/genericTeamWorkflows";

const api = vi.hoisted(() => ({ flows: vi.fn(), runs: vi.fn(), save: vi.fn() }));
vi.mock("../../../api/genericTeamWorkflows", async importOriginal => ({
  ...await importOriginal<typeof import("../../../api/genericTeamWorkflows")>(),
  listTeamFlows: api.flows, listTeamFlowRuns: api.runs, saveTeamFlow: api.save,
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let client: QueryClient;
let state: ReturnType<typeof useWorkflowWorkspace>;
let initial: Flow;
function Probe() { state = useWorkflowWorkspace("team-a"); return null; }
async function flush() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); }
beforeEach(async () => {
  api.flows.mockReset(); api.runs.mockReset(); api.save.mockReset();
  initial = createWorkflow("已保存流程", "blank", []); initial.revision = 1;
  api.flows.mockResolvedValue({ schemaVersion: 1, teamId: "team-a", flows: [initial] });
  api.runs.mockResolvedValue({ teamId: "team-a", runs: [] });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>));
  await flush();
});
afterEach(() => { act(() => root.unmount()); host.remove(); client.clear(); });

it("keeps edits made while a save is in flight and adopts the saved revision", async () => {
  let finish!: (flow: Flow) => void;
  api.save.mockImplementation(() => new Promise<Flow>(resolve => { finish = resolve; }));
  act(() => state.editFlow(flow => ({ ...flow, name: "先保存的版本" })));
  let save!: ReturnType<typeof state.save>;
  act(() => { save = state.save(); });
  act(() => state.editFlow(flow => ({ ...flow, name: "保存期间继续编辑" })));
  await act(async () => { finish({ ...initial, name: "先保存的版本", revision: 2 }); await save; });
  await flush();
  expect(state.flow?.name).toBe("保存期间继续编辑");
  expect(state.flow?.revision).toBe(2);
  expect(state.dirty).toBe(true);
});

it("keeps API-only research supervisors outside the editable workflow workspace", async () => {
  const supervisor: Flow = { ...initial, id: "supervisor", steps: [
    { id: "source", label: "研究来源", kind: "research", owner: "", instruction: "",
      researchSource: { runId: "research-run", nodeId: "source_finding" } },
  ] };
  act(() => client.setQueryData(teamFlowKeys.flows("team-a"), {
    schemaVersion: 1, teamId: "team-a", flows: [supervisor, initial],
  }));
  await flush();
  expect(state.flows.map(item => item.id)).toEqual([initial.id]);
  expect(state.flow?.id).toBe(initial.id);
});

it("retains the draft and exposes a stale-revision save failure", async () => {
  api.save.mockRejectedValue(new Error("版本已变化，请刷新后重试。"));
  act(() => state.editFlow(flow => ({ ...flow, name: "本地草稿" })));
  await act(async () => { expect(await state.save()).toBeUndefined(); });
  expect(state.flow?.name).toBe("本地草稿");
  expect(state.dirty).toBe(true);
  expect(state.error).toContain("版本已变化");
});

it("keeps the initially selected flow when saving reorders the server cache", async () => {
  const other = { ...createWorkflow("另一条流程", "blank", []), revision: 1 };
  act(() => client.setQueryData(teamFlowKeys.flows("team-a"), { schemaVersion: 1, teamId: "team-a", flows: [initial, other] }));
  await flush();
  api.save.mockResolvedValue({ ...initial, name: "编辑后的流程", revision: 2 });
  act(() => state.editFlow(flow => ({ ...flow, name: "编辑后的流程" })));
  await act(async () => { await state.save(); });
  await flush();
  expect(state.flow?.id).toBe(initial.id);
  expect(state.flow?.name).toBe("编辑后的流程");
  expect(state.dirty).toBe(false);
});
