// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { GeneratedToolDeleteResponse, ToolRegistryItem, ToolRegistryPayload } from "../api/types";
import { queryKeys } from "../api/queryKeys";
import { deleteTool, fetchToolImage2Models, fetchToolRegistry, fetchWebSearchToolHealth, setGeneratedToolEnabled } from "../api/tools";
import { listAgentSummaries } from "../api/agents";
import { ToolsRoute } from "./ToolsRoute";

vi.mock("../i18n/useAppI18n", () => ({ useAppI18n: () => ({ lang: "zh", t: (key: string) => key, dictionaryReady: true }) }));
vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh", t: (key: string) => key }) }));
vi.mock("../api/tools", () => ({ fetchToolRegistry: vi.fn(), fetchToolImage2Models: vi.fn(), fetchWebSearchToolHealth: vi.fn(), bulkDeleteToolRegistry: vi.fn(), bulkSetGeneratedToolsEnabled: vi.fn(), deleteTool: vi.fn(), setGeneratedToolEnabled: vi.fn(), setToolImage2DefaultModel: vi.fn(), testTool: vi.fn() }));
vi.mock("../api/agents", () => ({ listAgentSummaries: vi.fn(), updateAgentToolPolicy: vi.fn(), validateAgentToolPolicy: vi.fn() }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root, host: HTMLDivElement, client: QueryClient;
function tool(id: string): ToolRegistryItem {
  return {
    id, name: id, description: id, source: "generated", category: "memory", categoryLabel: "memory", bundleIds: [], capabilityTags: [], riskTags: [], permissionTier: "high",
    status: "validated", enabled: true, validated: true, llmVisible: true, runtimeActive: true, deleteAllowed: true, blockReason: "", validationError: "", argsSchema: {},
    testPolicy: { mode: "blocked", callable: false, runtimeCall: false, simulated: false, reason: "blocked", argsPreview: {} },
    agentScopes: { main_agent: { visible: true, callable: true, llmVisible: true, runtimeActive: true, testable: false, blockReason: "" } }, createdAt: "", updatedAt: "before",
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const registry = () => client.getQueryData<ToolRegistryPayload>(queryKeys.tools())!;
const button = (text: string, within: ParentNode = host) => [...within.querySelectorAll<HTMLButtonElement>("button")].find(row => row.textContent?.trim() === text) ?? null;
async function click(element: HTMLElement | null) {
  expect(element).not.toBeNull();
  await act(async () => { element!.dispatchEvent(new MouseEvent("mousedown", { button: 0, bubbles: true })); element!.click(); });
}
async function select(id: string) { await click(host.querySelector(`[data-tool-id="${id}"] button`)); }
async function toggle() { await click(button("toolsDisable")); }
async function remove() {
  await click(button("deleteSelected"));
  await click(button("deleteSelected", document.querySelector('[role="dialog"]')!));
}
beforeEach(async () => {
  vi.resetAllMocks();
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(440);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(380);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const height = this.hasAttribute("data-index") ? 62 : 440;
    return { width: 380, height, top: 0, left: 0, bottom: height, right: 380, x: 0, y: 0, toJSON: () => ({}) };
  });
  // Keep invalidations pending so a refresh cannot hide a bad optimistic rollback.
  vi.mocked(fetchToolRegistry).mockImplementation(() => new Promise(() => {}));
  vi.mocked(fetchToolImage2Models).mockImplementation(() => new Promise(() => {}));
  vi.mocked(fetchWebSearchToolHealth).mockImplementation(() => new Promise(() => {}));
  vi.mocked(listAgentSummaries).mockImplementation(() => new Promise(() => {}));
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity }, mutations: { retry: false } } });
  client.setQueryData(queryKeys.tools(), {
    schemaVersion: 1, mode: "runtime", storagePath: "fixture", counts: { total: 2, builtIn: 0, generated: 2, llmVisible: 2, runtimeActive: 2, enabledGenerated: 2, invalidGenerated: 0 }, agentScopes: [], toolBundles: [], tools: [tool("a"), tool("b")],
  } satisfies ToolRegistryPayload);
  client.setQueryData(queryKeys.agents(), []);
  client.setQueryData(queryKeys.toolImage2Models(), { selectedModel: { modelRef: "", discoveredModels: [] }, models: [] });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/agents/tools?view=library"]}><ToolsRoute /></MemoryRouter></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); vi.restoreAllMocks(); });

it("rolls back failed enable A without reverting completed enable B or registry metadata", async () => {
  const first = deferred<ToolRegistryItem>();
  vi.mocked(setGeneratedToolEnabled).mockImplementation(id => id === "a" ? first.promise : Promise.resolve({ ...tool("b"), enabled: false, runtimeActive: false, llmVisible: false, updatedAt: "saved-b" }));
  await select("a"); await toggle(); await select("b"); await toggle();
  await act(async () => { client.setQueryData(queryKeys.tools(), { ...registry(), storagePath: "new-metadata" }); });
  await act(async () => { first.reject(new Error("A refused")); });
  expect(registry().tools.find(row => row.id === "a")?.enabled).toBe(true);
  expect(registry().tools.find(row => row.id === "b")?.enabled).toBe(false);
  expect(registry().storagePath).toBe("new-metadata");
  expect(registry().counts.enabledGenerated).toBe(1);
});

it("does not roll back a later authoritative change to the enable target", async () => {
  const first = deferred<ToolRegistryItem>(); vi.mocked(setGeneratedToolEnabled).mockReturnValue(first.promise);
  await select("a"); await toggle();
  const newer = { ...tool("a"), name: "saved after start", enabled: false, updatedAt: "newer" };
  await act(async () => { client.setQueryData(queryKeys.tools(), { ...registry(), tools: registry().tools.map(row => row.id === "a" ? newer : row) }); });
  await act(async () => { first.reject(new Error("A refused")); });
  expect(registry().tools.find(row => row.id === "a")).toEqual(newer);
});

it("keeps delete A visible until confirmation and preserves B edits when A fails", async () => {
  const first = deferred<GeneratedToolDeleteResponse>(); vi.mocked(deleteTool).mockReturnValue(first.promise);
  vi.mocked(setGeneratedToolEnabled).mockResolvedValue({ ...tool("b"), enabled: false, runtimeActive: false, llmVisible: false });
  await select("a"); await remove();
  expect(registry().tools.map(row => row.id)).toEqual(["a", "b"]);
  await select("b"); await toggle();
  await act(async () => { first.reject(new Error("A refused")); });
  expect(registry().tools.find(row => row.id === "b")?.enabled).toBe(false);
  expect(registry().counts.total).toBe(2);
  expect(host.querySelector('#agent-tools-detail h2')?.textContent).toBe("b");
});

it("a failed delete A does not resurrect a separately deleted B", async () => {
  const first = deferred<GeneratedToolDeleteResponse>();
  vi.mocked(deleteTool).mockImplementation(id => id === "a" ? first.promise : Promise.resolve({ deleted: true, toolId: "b", summary: "deleted B" }));
  await select("a"); await remove(); await select("b"); await remove();
  await act(async () => { first.reject(new Error("A refused")); });
  expect(registry().tools.map(row => row.id)).toEqual(["a"]);
  expect(registry().counts.total).toBe(1);
});

it("a late confirmed deletion clears only A and preserves navigation to B", async () => {
  const first = deferred<GeneratedToolDeleteResponse>(); vi.mocked(deleteTool).mockReturnValue(first.promise);
  await select("a"); await remove(); await select("b");
  await act(async () => { first.resolve({ deleted: true, toolId: "a", summary: "deleted A" }); });
  expect(registry().tools.map(row => row.id)).toEqual(["b"]);
  expect(host.querySelector('#agent-tools-detail h2')?.textContent).toBe("b");
});

it("labels a lost enable reply unconfirmed and does not automatically repeat the write", async () => {
  vi.mocked(setGeneratedToolEnabled).mockRejectedValue(new TypeError("connection lost"));
  await select("a"); await toggle();
  expect(host.textContent).toContain("启用状态尚未确认");
  expect(setGeneratedToolEnabled).toHaveBeenCalledTimes(1);
  expect(registry().tools.find(row => row.id === "a")?.enabled).toBe(true);
});

it("retains a tool when the response does not confirm that target was deleted", async () => {
  vi.mocked(deleteTool).mockResolvedValue({ deleted: false, toolId: "a", summary: "not confirmed" });
  await select("a"); await remove();
  expect(registry().tools.map(row => row.id)).toEqual(["a", "b"]);
  expect(host.textContent).toContain("删除结果尚未确认");
  expect(deleteTool).toHaveBeenCalledTimes(1);
});

it("keeps A busy across concurrent B work and prevents another write after returning to A", async () => {
  const a = deferred<ToolRegistryItem>(), b = deferred<ToolRegistryItem>();
  vi.mocked(setGeneratedToolEnabled).mockImplementation(id => id === "a" ? a.promise : b.promise);
  await select("a"); await toggle(); await select("b"); await toggle(); await select("a");
  const pendingToggle = button("toolsEnable");
  expect(pendingToggle?.disabled).toBe(true);
  await click(pendingToggle);
  expect(setGeneratedToolEnabled).toHaveBeenCalledTimes(2);
  await act(async () => { b.resolve({ ...tool("b"), enabled: false }); });
  expect(button("toolsEnable")?.disabled).toBe(true);
  await act(async () => { a.resolve({ ...tool("a"), enabled: false }); });
  expect(button("toolsEnable")?.disabled).toBe(false);
});

it("a duplicate submission cannot release the original tool write", async () => {
  const first = deferred<ToolRegistryItem>(); vi.mocked(setGeneratedToolEnabled).mockReturnValue(first.promise);
  await select("a");
  const toggleButton = button("toolsDisable")!;
  await act(async () => { toggleButton.click(); toggleButton.click(); });
  expect(setGeneratedToolEnabled).toHaveBeenCalledTimes(1);
  expect(button("toolsEnable")?.disabled).toBe(true);
  expect(button("deleteSelected")?.disabled).toBe(true);
  await act(async () => { first.resolve({ ...tool("a"), enabled: false }); });
  expect(button("toolsEnable")?.disabled).toBe(false);
});
