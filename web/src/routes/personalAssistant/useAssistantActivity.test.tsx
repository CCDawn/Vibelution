// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import { useAssistantActivity } from "./useAssistantActivity";
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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
