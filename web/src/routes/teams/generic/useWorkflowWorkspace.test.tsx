/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Flow, Run } from "./workflowModel";
import { readWorkflowLoadingShape } from "./workflowLoadingShape";
import { useWorkflowWorkspace } from "./useWorkflowWorkspace";
import { createWorkflow } from "./workflowTemplates";
import { teamFlowKeys } from "../../../api/genericTeamWorkflows";

const api = vi.hoisted(() => ({ flows: vi.fn(), runs: vi.fn(), save: vi.fn(), start: vi.fn(), command: vi.fn() }));
vi.mock("../../../api/genericTeamWorkflows", async importOriginal => ({
  ...await importOriginal<typeof import("../../../api/genericTeamWorkflows")>(),
  listTeamFlows: api.flows, listTeamFlowRuns: api.runs, saveTeamFlow: api.save,
  startTeamFlowRun: api.start, commandTeamFlowRun: api.command,
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let client: QueryClient;
let state: ReturnType<typeof useWorkflowWorkspace>;
let initial: Flow;
function Probe({ teamId = "team-a" }: { teamId?: string }) { state = useWorkflowWorkspace(teamId); return null; }
async function selectTeam(teamId: string, flows: Flow[]) {
  client.setQueryData(teamFlowKeys.flows(teamId), { schemaVersion: 1, teamId, flows });
  client.setQueryData(teamFlowKeys.runs(teamId), { teamId, runs: [] });
  await act(async () => root.render(<QueryClientProvider client={client}><Probe teamId={teamId} /></QueryClientProvider>));
  await flush();
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
function makeRun(flow: Flow, id = "run-a"): Run {
  return { id, flow, revision: 1, status: "running", current: 0, values: {}, messages: [] } as unknown as Run;
}
async function flush() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); }); }
beforeEach(async () => {
  api.flows.mockReset(); api.runs.mockReset(); api.save.mockReset(); api.start.mockReset(); api.command.mockReset();
  initial = createWorkflow("已保存流程", "blank", []); initial.revision = 1;
  api.flows.mockResolvedValue({ schemaVersion: 1, teamId: "team-a", flows: [initial] });
  api.runs.mockImplementation((teamId: string) => Promise.resolve(client.getQueryData(teamFlowKeys.runs(teamId)) ?? { teamId, runs: [] }));
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>));
  await flush();
});

it("isolates pending saves and drafts across teams, including matching flow IDs", async () => {
  const a = deferred<Flow>(); const b = deferred<Flow>();
  api.save.mockImplementation((team: string) => team === "team-a" ? a.promise : b.promise);
  act(() => state.editFlow(flow => ({ ...flow, name: "A draft" })));
  let saveA!: ReturnType<typeof state.save>;
  act(() => { saveA = state.save(); void state.save(); });
  expect(api.save).toHaveBeenCalledTimes(1);
  await selectTeam("team-b", [{ ...initial, name: "B saved" }]);
  expect(state.flow?.name).toBe("B saved");
  expect(state.saving).toBe(false);
  act(() => state.editFlow(flow => ({ ...flow, name: "B draft" })));
  let saveB!: ReturnType<typeof state.save>;
  act(() => { saveB = state.save(); });
  expect(api.save).toHaveBeenCalledTimes(2);
  await act(async () => { a.resolve({ ...initial, name: "A draft", revision: 2 }); expect(await saveA).toBeUndefined(); });
  expect(state.flow?.name).toBe("B draft");
  expect(state.flow?.revision).toBe(1);
  expect(state.saving).toBe(true);
  await act(async () => { b.resolve({ ...initial, name: "B draft", revision: 2 }); await saveB; });
  expect(state.dirty).toBe(false);
  await selectTeam("team-a", [{ ...initial, name: "A draft", revision: 2 }]);
  expect(state.flow?.name).toBe("A draft");
  expect(state.flow?.revision).toBe(2);
});

it("allows another flow to save while one is pending and retains both edits", async () => {
  const other = { ...initial, id: "other", name: "other" };
  act(() => client.setQueryData(teamFlowKeys.flows("team-a"), { schemaVersion: 1, teamId: "team-a", flows: [initial, other] }));
  await flush();
  const pending = deferred<Flow>();
  api.save.mockImplementation((_team: string, flow: Flow) => flow.id === initial.id ? pending.promise : Promise.resolve({ ...flow, revision: 2 }));
  act(() => state.editFlow(flow => ({ ...flow, name: "A draft" })));
  let saveA!: ReturnType<typeof state.save>;
  act(() => { saveA = state.save(); });
  act(() => state.selectFlow(other.id));
  expect(state.saving).toBe(false);
  act(() => state.editFlow(flow => ({ ...flow, name: "other draft" })));
  await act(async () => { await state.save(); });
  expect(api.save).toHaveBeenCalledTimes(2);
  await act(async () => { pending.resolve({ ...initial, name: "A draft", revision: 2 }); expect(await saveA).toBeUndefined(); });
  expect(state.flow?.name).toBe("other draft");
});

it.each(["start", "command"] as const)("scopes %s occupancy and late selection to its team", async operation => {
  const a = deferred<Run>(); const b = deferred<Run>();
  api[operation].mockImplementation((team: string) => team === "team-a" ? a.promise : b.promise);
  if (operation === "command") {
    act(() => client.setQueryData(teamFlowKeys.runs("team-a"), { teamId: "team-a", runs: [makeRun(initial)] }));
    await flush(); act(() => state.selectRun("run-a"));
  }
  const submit = () => operation === "start" ? state.start(state.flow!, {}, "launch") : state.command("stop");
  let requestA!: ReturnType<typeof submit>;
  act(() => { requestA = submit(); void submit(); });
  expect(api[operation]).toHaveBeenCalledTimes(1);
  await selectTeam("team-b", [{ ...initial, name: "B" }]);
  expect(state.pending).toBe(false);
  if (operation === "command") {
    act(() => client.setQueryData(teamFlowKeys.runs("team-b"), { teamId: "team-b", runs: [makeRun(state.flow!, "run-b")] }));
    await flush(); act(() => state.selectRun("run-b"));
  }
  let requestB!: ReturnType<typeof submit>;
  act(() => { requestB = submit(); });
  expect(api[operation]).toHaveBeenCalledTimes(2);
  await act(async () => { a.resolve(makeRun(initial)); expect(await requestA).toBeUndefined(); });
  expect(state.pending).toBe(true);
  expect(state.run?.id).not.toBe("run-a");
  const resultB = makeRun(state.flow!, "run-b");
  await act(async () => { b.resolve(resultB); await requestB; });
  expect(client.getQueryData<{ runs: Run[] }>(teamFlowKeys.runs("team-a"))?.runs[0].id).toBe("run-a");
  expect(state.run?.id).toBe("run-b");
});

it.each(["start", "command"] as const)("allows another flow to %s while one is pending", async operation => {
  const other = { ...initial, id: "flow-b", name: "B" };
  act(() => {
    client.setQueryData(teamFlowKeys.flows("team-a"), { schemaVersion: 1, teamId: "team-a", flows: [initial, other] });
    client.setQueryData(teamFlowKeys.runs("team-a"), { teamId: "team-a", runs: [makeRun(initial), makeRun(other, "run-b")] });
  });
  await flush();
  act(() => state.selectRun("run-a"));
  const pending = deferred<Run>();
  api[operation].mockReturnValueOnce(pending.promise).mockResolvedValue(makeRun(other, "run-b"));
  const submit = () => operation === "start" ? state.start(state.flow!, {}, "launch") : state.command("stop");
  let requestA!: ReturnType<typeof submit>;
  act(() => { requestA = submit(); });
  act(() => state.selectFlow(other.id));
  if (operation === "command") act(() => state.selectRun("run-b"));
  expect(state.pending).toBe(false);
  await act(async () => { await submit(); });
  expect(api[operation]).toHaveBeenCalledTimes(2);
  await act(async () => { pending.resolve(makeRun(initial)); expect(await requestA).toBeUndefined(); });
  expect(state.flow?.id).toBe(other.id);
  expect(state.run?.id).toBe("run-b");
});
afterEach(() => { act(() => root.unmount()); host.remove(); client.clear(); });

it.each([false, true])("confirms an uncertain save from its exact snapshot and retains newer edits (edited=%s)", async edited => {
  act(() => state.editFlow(flow => ({ ...flow, name: "submitted" })));
  const snapshot = structuredClone(state.flow!);
  const readback = deferred<{ schemaVersion: number; teamId: string; flows: Flow[] }>();
  api.flows.mockReturnValue(readback.promise);
  api.save.mockRejectedValueOnce(Object.assign(new Error("结果尚未确认"), { name: "TeamFlowWriteOutcomeUnknownError" }));
  await act(async () => { await state.save(); });
  expect(state.saving).toBe(false);
  expect(api.save).toHaveBeenCalledTimes(1);
  if (edited) act(() => state.editFlow(flow => ({ ...flow, name: "newer draft" })));
  await act(async () => { readback.resolve({ schemaVersion: 1, teamId: "team-a", flows: [{ ...snapshot, revision: 2 }] }); });
  await flush();
  expect(state.flow?.revision).toBe(2);
  expect(state.flow?.name).toBe(edited ? "newer draft" : "submitted");
  expect(state.dirty).toBe(edited);
  if (!edited) act(() => state.editFlow(flow => ({ ...flow, description: "next change" })));
  api.save.mockImplementation(async (_team: string, flow: Flow) => ({ ...flow, revision: flow.revision + 1 }));
  await act(async () => { await state.save(); });
  expect(api.save.mock.calls[1][1].revision).toBe(2);
});

it.each(["content", "policy", "revision"])("keeps a revision conflict for mismatching uncertain-save readback (%s)", async mismatch => {
  act(() => state.editFlow(flow => ({ ...flow, name: "submitted" })));
  const remote = { ...state.flow!, name: mismatch === "content" ? "other writer" : "submitted", revision: mismatch === "revision" ? 3 : 2,
    ...(mismatch === "policy" ? { failureRecovery: { repairFlowId: "other" } as Flow["failureRecovery"] } : {}) };
  api.flows.mockResolvedValue({ schemaVersion: 1, teamId: "team-a", flows: [remote] });
  api.save.mockRejectedValueOnce(Object.assign(new Error("结果尚未确认"), { name: "TeamFlowWriteOutcomeUnknownError" }));
  await act(async () => { await state.save(); });
  await flush();
  expect(state.flow?.name).toBe("submitted");
  expect(state.flow?.revision).toBe(1);
  expect(state.dirty).toBe(true);
  api.save.mockRejectedValueOnce(new Error("版本已变化"));
  await act(async () => { await state.save(); });
  expect(api.save.mock.calls[1][1].revision).toBe(1);
  expect(state.error).toContain("版本已变化");
});

it("confirms a matching read that arrived before the write timeout even when refetch shares its cache object", async () => {
  act(() => state.editFlow(flow => ({ ...flow, name: "submitted" })));
  const snapshot = structuredClone(state.flow!);
  let reject!: (error: Error) => void;
  api.save.mockReturnValueOnce(new Promise<Flow>((_resolve, fail) => { reject = fail; }));
  let request!: ReturnType<typeof state.save>;
  act(() => { request = state.save(); });
  const authority = { schemaVersion: 1, teamId: "team-a", flows: [{ ...snapshot, revision: 2 }] };
  act(() => client.setQueryData(teamFlowKeys.flows("team-a"), authority));
  await flush();
  expect(state.flow?.revision).toBe(1);
  const cached = client.getQueryData(teamFlowKeys.flows("team-a"));
  api.flows.mockResolvedValue(authority);
  await act(async () => { reject(Object.assign(new Error("结果尚未确认"), { name: "TeamFlowWriteOutcomeUnknownError" })); await request; });
  await flush();
  expect(client.getQueryData(teamFlowKeys.flows("team-a"))).toBe(cached);
  expect(state.saving).toBe(false);
  expect(state.flow?.revision).toBe(2);
  act(() => state.editFlow(flow => ({ ...flow, description: "next change" })));
  api.save.mockImplementation(async (_team: string, flow: Flow) => ({ ...flow, revision: flow.revision + 1 }));
  await act(async () => { await state.save(); });
  expect(api.save.mock.calls[1][1].revision).toBe(2);
});

it("accepts server step defaults when confirming the exact uncertain snapshot", async () => {
  act(() => state.editFlow(flow => ({ ...flow, name: "submitted" })));
  const saved = { ...state.flow!, revision: 2, failureRecovery: null,
    steps: state.flow!.steps.map(step => ({ ...step, resultContract: "text" as const, researchSource: null, sessionSource: null })) };
  api.flows.mockResolvedValue({ schemaVersion: 1, teamId: "team-a", flows: [saved] });
  api.save.mockRejectedValueOnce(Object.assign(new Error("结果尚未确认"), { name: "TeamFlowWriteOutcomeUnknownError" }));
  await act(async () => { await state.save(); });
  await flush();
  expect(state.flow?.revision).toBe(2);
  expect(state.dirty).toBe(false);
  expect(api.save).toHaveBeenCalledTimes(1);
});

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

it.each(["research", "session"] as const)("keeps API-only %s supervisors outside the editable workflow workspace", async (kind) => {
  const supervisor: Flow = { ...initial, id: "supervisor", steps: [
    { id: "source", label: "原生来源", kind, owner: "", instruction: "",
      ...(kind === "research" ? { researchSource: { runId: "research-run", nodeId: "source_finding" } }
        : { sessionSource: { sessionId: "session-1", turnId: "turn-1", agentId: "agent-1" } }) },
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

it("records server structure without letting unsaved drafts replace the loading hint", async () => {
  const expected = initial.steps.map(step => step.kind);
  act(() => state.addFlow(createWorkflow("新草稿", "analysis", [])));
  expect(readWorkflowLoadingShape("team-a")?.[0].steps.map(step => step.kind)).toEqual(expected);
  await act(async () => { client.setQueryData(teamFlowKeys.flows("team-a"), {schemaVersion:1,teamId:"team-a",flows:[]}); });
  await flush();
  expect(readWorkflowLoadingShape("team-a")).toEqual([]);
});
