// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import type { ComputerState } from "../../api/types/personalAssistantComputer";
import type { SessionDetail } from "../../api/types/chat";
import type { PetActivity } from "../../api/types/petActivity";
import { fetchSessionDetail } from "../../api/chat";
import { fetchPetActivity } from "../../api/pet";
import { fetchPersonalAssistantComputer } from "../../api/personalAssistantComputer";
import { useAssistantActivity } from "./useAssistantActivity";
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
vi.mock("../../api/chat", () => ({ fetchSessionDetail: vi.fn() }));
vi.mock("../../api/pet", () => ({ fetchPetActivity: vi.fn() }));
vi.mock("../../api/personalAssistantComputer", () => ({ fetchPersonalAssistantComputer: vi.fn(async () => ({
  available: false, status: "idle", message: "", grantId: null, window: null, pending: null,
})) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue({
    available: false, status: "idle", message: "", grantId: null, window: null, pending: null,
  });
});

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

it("reduces collapsed idle reads while keeping active, unread and fallback refreshes", async () => {
  vi.useFakeTimers();
  focusManager.setFocused(true);
  const assistant = { agentId: "poll-agent", directSessionId: "poll-session", displayName: "Assistant", status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" } satisfies PersonalAssistant;
  const idle: PetActivity = { schemaVersion: 1, aggregateTone: "idle", animationState: "idle", activeCount: 0, attentionCount: 0, generatedAt: "", sessions: [] };
  let activity = idle;
  let detail = { id: assistant.directSessionId, agentId: assistant.agentId, sessionKind: "main", messages: [] } as unknown as SessionDetail;
  const computerIdle: ComputerState = { available: false, status: "idle", message: "", grantId: null, window: null, pending: null };
  vi.mocked(fetchPetActivity).mockReset().mockImplementation(async () => activity);
  vi.mocked(fetchSessionDetail).mockReset().mockImplementation(async () => detail);
  vi.mocked(fetchPersonalAssistantComputer).mockReset().mockResolvedValue(computerIdle);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnMount: false, gcTime: Infinity } } });
  const replyKey = queryKeys.personalAssistantReplies(assistant.agentId, assistant.directSessionId);
  client.setQueryData(queryKeys.petActivity(), idle);
  client.setQueryData(replyKey, detail);
  client.setQueryData(queryKeys.personalAssistantComputer(), computerIdle);
  let reading = false;
  let enabled = true;
  function Probe() { const state = useAssistantActivity({ enabled, assistant, reading }); return <output>{state.unreadCount}</output>; }
  const container = document.createElement("div"); document.body.appendChild(container); const root = createRoot(container);
  const render = () => act(async () => root.render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>));
  const advance = async (seconds: number) => {
    for (let i = 0; i < seconds; i++) await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    await act(async () => { await vi.advanceTimersByTimeAsync(5); });
    await act(async () => { await vi.advanceTimersByTimeAsync(5); });
  };
  try {
    await render();
    await advance(60);
    // Same idle minute used to perform 20 + 60 + 20 requests.
    expect(fetchPetActivity).toHaveBeenCalledTimes(20);
    expect(fetchPersonalAssistantComputer).toHaveBeenCalledTimes(4);
    expect(fetchSessionDetail).toHaveBeenCalledTimes(2);

    activity = { ...idle, sessions: [{ sessionId: assistant.directSessionId, agentId: "another-agent", title: "", agentDisplayName: "", tone: "completed", phase: "completed", updatedAt: "unrelated" }] };
    await advance(6);
    expect(fetchSessionDetail).toHaveBeenCalledTimes(2); // another Agent cannot drive this mailbox

    detail = { ...detail, messages: [{ role: "assistant", turnId: "poll-turn", status: "completed", turnItems: [{ type: "agent_message", phase: "final_answer", status: "completed", itemId: "poll-final", text: "Done" }] }] } as SessionDetail;
    activity = { ...idle, sessions: [{ sessionId: assistant.directSessionId, agentId: assistant.agentId, title: "", agentDisplayName: "", tone: "completed", phase: "completed", updatedAt: "new-reply" }] };
    await advance(3);
    expect(fetchSessionDetail).toHaveBeenCalledTimes(3);
    expect(container.textContent).toBe("1");
    await advance(6);
    expect(fetchSessionDetail).toHaveBeenCalledTimes(5); // recent completion keeps the original 3s cadence

    const repliesBefore = vi.mocked(fetchSessionDetail).mock.calls.length;
    const computerBefore = vi.mocked(fetchPersonalAssistantComputer).mock.calls.length;
    reading = true;
    await render();
    await advance(6);
    expect(vi.mocked(fetchSessionDetail).mock.calls.length - repliesBefore).toBe(2);
    expect(vi.mocked(fetchPersonalAssistantComputer).mock.calls.length - computerBefore).toBe(6);

    reading = false;
    const granted: ComputerState = { ...computerIdle, grantId: "grant", status: "working" };
    vi.mocked(fetchPersonalAssistantComputer).mockResolvedValue(granted);
    await act(async () => { client.setQueryData(queryKeys.personalAssistantComputer(), granted); });
    activity = { ...activity, sessions: activity.sessions.map(row => ({ ...row, tone: "running", phase: "tooling" })) };
    await render();
    await advance(3); // observe activity on the regular lightweight poll
    const activeReplies = vi.mocked(fetchSessionDetail).mock.calls.length;
    const activeComputer = vi.mocked(fetchPersonalAssistantComputer).mock.calls.length;
    await advance(6);
    expect(vi.mocked(fetchSessionDetail).mock.calls.length - activeReplies).toBe(2);
    expect(vi.mocked(fetchPersonalAssistantComputer).mock.calls.length - activeComputer).toBe(6);

    // Even if activity omits a reply, the idle fallback still reads native messages.
    activity = idle;
    await advance(3);
    const unreadBeforeFallback = Number(container.textContent);
    detail = { ...detail, messages: [...detail.messages, { ...detail.messages[0], turnId: "fallback-turn" }] };
    await advance(30);
    expect(Number(container.textContent)).toBe(unreadBeforeFallback + 1);
    expect(client.getQueryData<SessionDetail>(replyKey)?.messages).toHaveLength(2);

    vi.mocked(fetchSessionDetail).mockRejectedValueOnce(new Error("temporarily unavailable"));
    await act(async () => { await client.refetchQueries({ queryKey: replyKey, exact: true }); });
    const failedReads = vi.mocked(fetchSessionDetail).mock.calls.length;
    await advance(3);
    expect(fetchSessionDetail).toHaveBeenCalledTimes(failedReads + 1);
    expect(client.getQueryState(replyKey)?.status).toBe("success");

    const counts = [fetchPetActivity, fetchPersonalAssistantComputer, fetchSessionDetail].map(fn => vi.mocked(fn).mock.calls.length);
    enabled = false;
    await render();
    await advance(60);
    expect([fetchPetActivity, fetchPersonalAssistantComputer, fetchSessionDetail].map(fn => vi.mocked(fn).mock.calls.length)).toEqual(counts);
  } finally {
    await act(async () => root.unmount()); client.clear(); container.remove();
    focusManager.setFocused(undefined); vi.useRealTimers();
  }
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
