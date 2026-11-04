// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useLauncherAssistantBudget } from "./useLauncherAssistantBudget";
import type { ChatComposerBudgetControl } from "../chat/ChatComposerBudgetPopover";

let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;
let control: ChatComposerBudgetControl | undefined;
let invoke: ReturnType<typeof vi.fn>;
async function settle() { await act(async () => { await new Promise(done => setTimeout(done, 10)); }); }
async function render() {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  invoke = vi.fn(async request => request.operation === "budgetParameters"
    ? { revision: 3, maxCallsPerTurn: 16 }
    : { revision: 4, maxCallsPerTurn: request.maxCallsPerTurn });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Harness() { control = useLauncherAssistantBudget("s", "a", "zh"); return null; }
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>));
  await settle();
}
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined; client?.clear(); container?.remove(); vi.unstubAllGlobals();
});

describe("Launcher assistant budget state", () => {
  it("does not let a read started during a save roll back the confirmed quota", async () => {
    await render();
    let confirm!: (value: unknown) => void;
    let oldRead!: (value: unknown) => void;
    const write = new Promise(done => { confirm = done; });
    const read = new Promise(done => { oldRead = done; });
    invoke.mockImplementation(async request => request.operation === "setBudgetParameters" ? write : read);
    await act(async () => control!.onSave({ revision: 3, maxCallsPerTurn: 0 }));
    let refresh!: Promise<void>;
    await act(async () => { refresh = client.invalidateQueries({ queryKey: ["launcher-assistant", "budget"] }); });
    await act(async () => confirm({ revision: 4, maxCallsPerTurn: 0 }));
    await settle();
    expect(control?.maxCallsPerTurn).toBe(0);
    await act(async () => { oldRead({ revision: 3, maxCallsPerTurn: 16 }); await refresh; });
    await settle();
    expect(control?.revision).toBe(4);
    expect(control?.maxCallsPerTurn).toBe(0);
  });
  it("keeps the confirmed limit until saving succeeds and suppresses duplicate writes", async () => {
    await render();
    expect(control?.maxCallsPerTurn).toBe(16);
    let resolve!: (value: unknown) => void;
    const response = new Promise(done => { resolve = done; });
    invoke.mockImplementation(async request => request.operation === "setBudgetParameters" ? response : { revision: 3, maxCallsPerTurn: 16 });
    await act(async () => {
      control!.onSave({ revision: 3, maxCallsPerTurn: 0 });
      control!.onSave({ revision: 3, maxCallsPerTurn: 32 });
    });
    expect(control?.pending).toBe(true);
    expect(control?.maxCallsPerTurn).toBe(16);
    expect(invoke.mock.calls.filter(([request]) => request.operation === "setBudgetParameters")).toHaveLength(1);
    await act(async () => resolve({ revision: 4, maxCallsPerTurn: 0 }));
    await settle();
    expect(control?.maxCallsPerTurn).toBe(0);
    expect(control?.pending).toBe(false);
  });

  it("refreshes a conflict without replaying the rejected change", async () => {
    await render();
    invoke.mockImplementation(async request => {
      if (request.operation === "setBudgetParameters") throw new Error("ASSISTANT_BUDGET_CONFLICT");
      return { revision: 5, maxCallsPerTurn: 64 };
    });
    await act(async () => control!.onSave({ revision: 3, maxCallsPerTurn: 0 }));
    await settle();
    expect(control?.revision).toBe(5);
    expect(control?.maxCallsPerTurn).toBe(64);
    expect(control?.errorMessage).toContain("别处更新");
    expect(invoke.mock.calls.filter(([request]) => request.operation === "setBudgetParameters")).toHaveLength(1);
  });
});
