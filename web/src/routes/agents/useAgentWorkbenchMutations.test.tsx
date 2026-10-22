// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "../../api/agents";
import { FetchJsonHttpError } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type { AgentConfigWorkspace, AgentConfigWorkspaceAgent } from "../../api/types";
import { archivedWorkspaceCache, updatedAgentWorkspaceCache } from "../agentWorkspaceCache";
import { optimisticArchivedAgent } from "./agentRouteBulkModel";
import { useAgentWorkbenchMutations, type UseAgentWorkbenchMutationsOptions } from "./useAgentWorkbenchMutations";

vi.mock("../../api/agents", async importOriginal => ({
  ...await importOriginal<typeof import("../../api/agents")>(),
  archiveAgent: vi.fn(), bulkArchiveAgents: vi.fn(), fetchAgentArchiveState: vi.fn(),
}));
vi.mock("../../app/userActionTelemetry", () => ({ startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn() }) }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const agent = (agentId: string, status = "active") => ({ agentId, displayName: agentId, status, references: [], health: [], runtimeStatus: { state: "idle" } }) as unknown as AgentConfigWorkspaceAgent;
let root: Root, node: HTMLDivElement, client: QueryClient;
let selected: string, pane: string, notice: ReturnType<typeof vi.fn>;
let mutations: ReturnType<typeof useAgentWorkbenchMutations>;
const current = () => client.getQueryData<AgentConfigWorkspace>(queryKeys.agentConfigWorkspace())!;
function Consumer() {
  mutations = useAgentWorkbenchMutations({
    lang: "zh", copy: {}, setNotice: notice,
    chatWorkspaceCache: { afterAgentArchived: vi.fn().mockResolvedValue(undefined) },
    getWorkspace: current, getSelectedAgentId: () => selected, getActivePane: () => pane,
    getSelectedAgent: () => current().agents.find(row => row.agentId === selected),
    setSelectedAgentId: (value: string) => { selected = value; },
    setActivePane: (value: string) => { pane = value; },
    agentLabel: (value: AgentConfigWorkspaceAgent) => value.displayName,
    archivedWorkspaceCache, updatedAgentWorkspaceCache, optimisticArchivedAgent,
  } as unknown as UseAgentWorkbenchMutationsOptions);
  return null;
}
beforeEach(async () => {
  vi.resetAllMocks(); selected = "a"; pane = "config"; notice = vi.fn();
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(queryKeys.agentConfigWorkspace(), {
    agents: [agent("a"), agent("b")], modeBindings: {}, chatRooms: [], references: {}, groups: [], summary: {},
    health: { issues: [], counts: { blocking: 0, warning: 0, info: 0 }, byAgent: {} },
  });
  client.setQueryData(queryKeys.agentSummary(true), [agent("a"), agent("b")]);
  node = document.createElement("div"); document.body.append(node); root = createRoot(node);
  await act(async () => root.render(<QueryClientProvider client={client}><Consumer /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });

it("a failed archive rolls back only its Agent and preserves another completed archive", async () => {
  const first = deferred<AgentConfigWorkspaceAgent>();
  vi.mocked(api.archiveAgent).mockImplementation(id => id === "a" ? first.promise : Promise.resolve(agent("b", "archived")));
  let a!: Promise<unknown>;
  await act(async () => { a = mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }).catch(error => error); });
  selected = "b";
  await act(async () => { await mutations.archiveAgentMutation.mutateAsync({ agentId: "b" }); });
  await act(async () => { first.reject(new FetchJsonHttpError("refused", { status: 400 })); await a; });
  expect(current().agents.find(row => row.agentId === "a")?.status).toBe("active");
  expect(current().agents.find(row => row.agentId === "b")?.status).toBe("archived");
});

it("a late archive reply does not clear the Agent and pane selected afterward", async () => {
  const first = deferred<AgentConfigWorkspaceAgent>();
  vi.mocked(api.archiveAgent).mockReturnValue(first.promise);
  let a!: Promise<unknown>;
  await act(async () => { a = mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }); });
  selected = "b"; pane = "activity";
  await act(async () => { first.resolve(agent("a", "archived")); await a; });
  expect(selected).toBe("b"); expect(pane).toBe("activity");
});

it("does not repeat a timed-out write when readback confirms archive success", async () => {
  vi.mocked(api.archiveAgent).mockRejectedValue(new DOMException("timed out", "TimeoutError"));
  vi.mocked(api.fetchAgentArchiveState).mockResolvedValue(agent("a", "archived"));
  await act(async () => { await mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }); });
  expect(api.archiveAgent).toHaveBeenCalledTimes(1);
  expect(api.fetchAgentArchiveState).toHaveBeenCalledWith("a");
  expect(current().agents.find(row => row.agentId === "a")?.status).toBe("archived");
  expect(notice.mock.calls.at(-1)?.[0].tone).toBe("success");
});

it("keeps an uncertain result retryable through readback without blindly repeating the write", async () => {
  vi.mocked(api.archiveAgent).mockRejectedValue(new TypeError("connection lost"));
  vi.mocked(api.fetchAgentArchiveState).mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValueOnce(agent("a", "archived"));
  await act(async () => { await mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }).catch(() => undefined); });
  expect(current().agents.find(row => row.agentId === "a")?.status).toBe("active");
  expect(notice.mock.calls.at(-1)?.[0].text).toContain("尚未确认");
  await act(async () => { await mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }); });
  expect(api.archiveAgent).toHaveBeenCalledTimes(1);
  expect(current().agents.find(row => row.agentId === "a")?.status).toBe("archived");
});

it("guards same-Agent reentry while allowing another Agent to finish independently", async () => {
  const first = deferred<AgentConfigWorkspaceAgent>();
  vi.mocked(api.archiveAgent).mockImplementation(id => id === "a" ? first.promise : Promise.resolve(agent("b", "archived")));
  let a!: Promise<unknown>;
  await act(async () => { a = mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }); });
  await act(async () => { await mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }).catch(() => undefined); });
  await act(async () => { await mutations.archiveAgentMutation.mutateAsync({ agentId: "b" }); });
  expect(api.archiveAgent).toHaveBeenCalledTimes(2);
  expect(mutations.isAgentArchivePending("a")).toBe(true);
  expect(mutations.isAgentArchivePending("b")).toBe(false);
  await act(async () => { first.resolve(agent("a", "archived")); await a; });
  expect(mutations.isAgentArchivePending("a")).toBe(false);
});

it("separates confirmed and unknown bulk results and releases every target for explicit recovery", async () => {
  vi.mocked(api.bulkArchiveAgents).mockRejectedValueOnce(new TypeError("reply lost"));
  vi.mocked(api.fetchAgentArchiveState).mockImplementation(id => Promise.resolve(agent(id, id === "a" ? "archived" : "active")));
  let outcome!: Awaited<ReturnType<typeof mutations.archiveAgents>>;
  await act(async () => { outcome = await mutations.archiveAgents(["a", "b"]); });
  expect(outcome.success.map(row => row.agentId)).toEqual(["a"]);
  expect(outcome.uncertain.map(row => row.agentId)).toEqual(["b"]);
  expect(outcome.failed).toEqual([]);
  expect(api.bulkArchiveAgents).toHaveBeenCalledTimes(1);
  expect(mutations.isAgentArchivePending("a")).toBe(false);
  expect(mutations.isAgentArchivePending("b")).toBe(false);

  vi.mocked(api.fetchAgentArchiveState).mockResolvedValueOnce(agent("b", "archived"));
  await act(async () => { outcome = await mutations.archiveAgents(["b"]); });
  expect(outcome.success.map(row => row.agentId)).toEqual(["b"]);
  expect(outcome.uncertain).toEqual([]);
  expect(api.bulkArchiveAgents).toHaveBeenCalledTimes(1);
});

it("allows bulk B while bulk A is unresolved and rejects only duplicate A", async () => {
  const a = deferred<Awaited<ReturnType<typeof mutations.archiveAgents>>>();
  const completed = (id: string) => ({ status: "completed", requestedAgentIds: [id], success: [agent(id, "archived")], skipped: [], failed: [], uncertain: [], summary: { requestedCount: 1, successCount: 1, skippedCount: 0, failedCount: 0 } });
  vi.mocked(api.bulkArchiveAgents).mockImplementation(<T,>(ids: string[]) =>
    (ids.includes("a") ? a.promise : Promise.resolve(completed("b"))) as Promise<T>);
  let pending!: Promise<unknown>;
  await act(async () => { pending = mutations.archiveAgents(["a"]); });
  await act(async () => {
    await expect(mutations.archiveAgents(["a"])).rejects.toThrow("仍在处理中");
    const b = await mutations.archiveAgents(["b"]);
    expect(b.success.map(row => row.agentId)).toEqual(["b"]);
  });
  expect(api.bulkArchiveAgents).toHaveBeenCalledTimes(2);
  expect(mutations.isAgentArchivePending("a")).toBe(true);
  expect(mutations.isAgentArchivePending("b")).toBe(false);
  await act(async () => { a.resolve(completed("a")); await pending; });
  expect(mutations.isAgentArchivePending("a")).toBe(false);
});

it("releases bulk targets even when the request and its readbacks all fail", async () => {
  vi.mocked(api.bulkArchiveAgents).mockRejectedValue(new TypeError("offline"));
  vi.mocked(api.fetchAgentArchiveState).mockRejectedValue(new TypeError("offline"));
  await act(async () => {
    const result = await mutations.archiveAgents(["a", "b"]);
    expect(result.uncertain).toHaveLength(2);
  });
  expect(mutations.isAgentArchivePending("a")).toBe(false);
  expect(mutations.isAgentArchivePending("b")).toBe(false);
  await act(async () => { await mutations.archiveAgents(["a"]); });
  expect(api.bulkArchiveAgents).toHaveBeenCalledTimes(1);
});

it("does not overwrite a newer authoritative edit with a late archive reply", async () => {
  const first = deferred<AgentConfigWorkspaceAgent>();
  vi.mocked(api.archiveAgent).mockReturnValue(first.promise);
  let pending!: Promise<unknown>;
  await act(async () => { pending = mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }); });
  const newer = { ...agent("a"), displayName: "saved later", configRevision: 9, updatedAt: "2026-10-23T02:00:00Z" };
  client.setQueryData(queryKeys.agentConfigWorkspace(), { ...current(), agents: [newer, agent("b")] });
  client.setQueryData(queryKeys.agentSummary(true), [newer, agent("b")]);
  await act(async () => {
    first.resolve({ ...agent("a", "archived"), configRevision: 8, updatedAt: "2026-10-23T01:00:00Z" });
    await pending;
  });
  expect(current().agents[0]).toMatchObject({ displayName: "saved later", status: "active", configRevision: 9 });
  expect(client.getQueryData<AgentConfigWorkspaceAgent[]>(queryKeys.agentSummary(true))?.[0]).toEqual(newer);
});

it("does not roll back a newer edit to the target when the archive is refused", async () => {
  const first = deferred<AgentConfigWorkspaceAgent>();
  vi.mocked(api.archiveAgent).mockReturnValue(first.promise);
  let pending!: Promise<unknown>;
  await act(async () => { pending = mutations.archiveAgentMutation.mutateAsync({ agentId: "a" }).catch(error => error); });
  const newer = { ...agent("a"), displayName: "changed while waiting" };
  client.setQueryData(queryKeys.agentConfigWorkspace(), { ...current(), agents: [newer, agent("b")] });
  await act(async () => { first.reject(new FetchJsonHttpError("refused", { status: 409 })); await pending; });
  expect(current().agents[0]).toEqual(newer);
});
