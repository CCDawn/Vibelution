/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { updateSessionModelParameters } from "../../api/chat";
import { FetchJsonHttpError } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type { SessionLlmModelOption, SessionLlmOptions } from "../../api/types";
import {
  useChatSessionDetailMutations,
  type UseChatSessionDetailMutationsOptions,
  type UseChatSessionDetailMutationsResult,
} from "./useChatSessionDetailMutations";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
vi.mock("../../api/chat", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/chat")>(),
  updateSessionModelParameters: vi.fn(),
}));

function options(sessionId: string, agentId = "shared-agent", configRevision = 5): SessionLlmOptions {
  return {
    sessionId,
    agentId,
    configRevision,
    currentModelId: "provider/model",
    currentReasoningEffort: "high",
    model: { modelRef: "provider/model" } as SessionLlmModelOption,
    contextWindow: configRevision === 5 ? 64_000 : 32_000,
    maxContextWindow: 128_000,
  };
}

describe("Agent model settings cache refresh", () => {
  it.each([
    { activeAfterSave: "session-a", conflict: false },
    { activeAfterSave: "session-b", conflict: false },
    { activeAfterSave: "session-b", conflict: true },
  ])("refreshes same-Agent settings with $activeAfterSave active (conflict=$conflict)", async ({ activeAfterSave, conflict }) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
    const a = options("session-a");
    const b = options("session-b");
    const c = options("session-c", "unrelated-agent");
    for (const payload of [a, b, c]) client.setQueryData(queryKeys.sessionLlmOptions(payload.sessionId), payload);
    client.setQueryData(queryKeys.session("session-b"), { agentId: "shared-agent" });
    const refetchB = vi.fn().mockResolvedValue(options("session-b", "shared-agent", 6));
    const observer = new QueryObserver(client, { queryKey: queryKeys.sessionLlmOptions("session-b"), queryFn: refetchB, staleTime: Infinity });
    const unsubscribe = observer.subscribe(() => undefined);
    let resolveSave!: (payload: SessionLlmOptions) => void;
    let rejectSave!: (error: Error) => void;
    vi.mocked(updateSessionModelParameters).mockReturnValueOnce(new Promise((resolve, reject) => { resolveSave = resolve; rejectSave = reject; }));
    const actions = { current: null as UseChatSessionDetailMutationsResult | null };
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    function Harness({ activeSessionId }: { activeSessionId: string }) {
      actions.current = useChatSessionDetailMutations({
        queryClient: client,
        chatWorkspaceCache: {} as UseChatSessionDetailMutationsOptions["chatWorkspaceCache"],
        activeSessionId,
        lang: "zh",
        describeError: (_error, fallback) => fallback,
        setSessionComposerErrors: () => undefined,
      });
      return null;
    }
    const render = (activeSessionId: string) => act(async () => root.render(
      <QueryClientProvider client={client}><Harness activeSessionId={activeSessionId} /></QueryClientProvider>,
    ));
    try {
      await render("session-a");
      let saved!: Promise<SessionLlmOptions>;
      await act(async () => {
        saved = actions.current!.sessionModelParametersMutation.mutateAsync({
          sessionId: "session-a",
          parameters: { expectedAgentId: "shared-agent", expectedModelRef: "provider/model", expectedConfigRevision: 5, contextWindow: 32_000, reasoningEffort: "high" },
        });
      });
      await render(activeAfterSave);
      await act(async () => {
        if (conflict) {
          rejectSave(new FetchJsonHttpError("revision conflict", { status: 409 }));
          await saved.catch(() => undefined);
        } else {
          resolveSave(options("session-a", "shared-agent", 6));
          await saved;
        }
      });
      await vi.waitFor(() => expect(refetchB).toHaveBeenCalledTimes(1));
      expect(client.getQueryData<SessionLlmOptions>(queryKeys.sessionLlmOptions("session-b"))?.sessionId).toBe("session-b");
      expect(client.getQueryData<SessionLlmOptions>(queryKeys.sessionLlmOptions("session-b"))?.configRevision).toBe(6);
      expect(client.getQueryData(queryKeys.sessionLlmOptions("session-c"))).toEqual(c);
      expect(client.getQueryState(queryKeys.sessionLlmOptions("session-c"))?.isInvalidated).toBe(false);
      expect(client.getQueryState(queryKeys.session("session-b"))?.isInvalidated).toBe(false);
      if (activeAfterSave === "session-a" && !conflict) {
        expect(client.getQueryData<SessionLlmOptions>(queryKeys.sessionLlmOptions("session-a"))?.configRevision).toBe(6);
        expect(client.getQueryState(queryKeys.sessionLlmOptions("session-a"))?.isInvalidated).toBe(false);
      } else {
        expect(client.getQueryData(queryKeys.sessionLlmOptions("session-a"))).toEqual(a);
        expect(client.getQueryState(queryKeys.sessionLlmOptions("session-a"))?.isInvalidated).toBe(true);
      }
    } finally {
      unsubscribe();
      await act(async () => root.unmount());
      host.remove();
      client.clear();
    }
  });
});
