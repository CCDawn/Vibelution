// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import type { ComputerState } from "../../api/types/personalAssistantComputer";
import { useAssistantActivity } from "./useAssistantActivity";
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
vi.mock("../../api/personalAssistantComputer", () => ({ fetchPersonalAssistantComputer: vi.fn(async () => ({
  available: false, status: "idle", message: "", grantId: null, window: null, pending: null,
})) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it.each([
  ["working", "tooling", "正在操作已授权窗口"],
  ["waiting_confirmation", "waiting", "电脑操作等待你确认"],
  ["paused", "idle", "电脑操作已暂停"],
  ["manual", "idle", "你正在操作电脑"],
] as const)("projects %s computer state onto the assistant without changing Session", async (status, animation, label) => {
  const assistant = { agentId: `computer-${status}`, directSessionId: `computer-session-${status}`, displayName: "Assistant", status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" } satisfies PersonalAssistant;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnMount: false, gcTime: Infinity } } });
  client.setQueryData(queryKeys.petActivity(), { schemaVersion: 1, aggregateTone: "idle", animationState: "idle", activeCount: 0, attentionCount: 0, generatedAt: "", sessions: [] });
  client.setQueryData(queryKeys.personalAssistantReplies(assistant.agentId, assistant.directSessionId), { id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "main", messages: [] });
  client.setQueryData(queryKeys.personalAssistantComputer(), { available: true, status, grantId: "grant", message: "", window: null, pending: null } satisfies ComputerState);
  function Probe() { const state = useAssistantActivity({ enabled: true, assistant, reading: false }); return <output data-animation={state.animationState}>{state.statusText}</output>; }
  const container = document.createElement("div"); document.body.appendChild(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>));
    expect(container.querySelector("output")?.dataset.animation).toBe(animation);
    expect(container.textContent).toBe(label);
  } finally { await act(async () => root.unmount()); client.clear(); container.remove(); }
});

it("expires staggered completion and new-message pulses while retaining unread state", async () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-18T00:00:00Z"));
  const assistant = { agentId: "overlap-agent", directSessionId: "overlap-session", displayName: "Assistant", status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" } satisfies PersonalAssistant;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnMount: false, gcTime: Infinity } } });
  client.setQueryData(queryKeys.petActivity(), { schemaVersion: 1, aggregateTone: "completed", animationState: "celebrating", activeCount: 0, attentionCount: 0, generatedAt: "", sessions: [] });
  const detail = { id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "main", messages: [] };
  const key = queryKeys.personalAssistantReplies(assistant.agentId, assistant.directSessionId);
  client.setQueryData(key, detail);
  function Probe() { const state = useAssistantActivity({ enabled: true, assistant, reading: false }); return <output data-animation={state.animationState}>{state.unreadCount}</output>; }
  const container = document.createElement("div"); document.body.appendChild(container); const root = createRoot(container);
  try {
    await act(async () => { root.render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>); });
    await act(async () => vi.advanceTimersByTimeAsync(500));
    await act(async () => { client.setQueryData(key, { ...detail, messages: [{ role: "assistant", turnId: "t2", status: "completed", turnItems: [{ type: "agent_message", phase: "final_answer", status: "completed", itemId: "final", text: "Done" }] }] }); await vi.advanceTimersByTimeAsync(5); });
    expect(container.querySelector("output")?.dataset.animation).toBe("celebrating");
    await act(async () => vi.advanceTimersByTimeAsync(950));
    expect(container.querySelector("output")?.dataset.animation).toBe("celebrating");
    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(container.querySelector("output")?.dataset.animation).toBe("idle");
    expect(container.textContent).toBe("1");
  } finally {
    await act(async () => root.unmount()); client.clear(); container.remove(); vi.useRealTimers();
  }
});
