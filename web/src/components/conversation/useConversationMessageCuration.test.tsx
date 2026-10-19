// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FetchJsonHttpError } from "../../api/client";
import {
  fetchSessionMessageCuration,
  setSessionMessageCuration,
  type SessionMessageCurationMutationResponse,
  type SessionMessageCurationResponse,
} from "../../api/chat";
import type { SessionMessageCurationAction } from "../../api/types";
import {
  useConversationMessageCuration,
  type UseConversationMessageCurationResult,
} from "./useConversationMessageCuration";

vi.mock("../../api/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/chat")>();
  return {
    ...actual,
    fetchSessionMessageCuration: vi.fn(),
    setSessionMessageCuration: vi.fn(),
  };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MESSAGE_ID = "message-1";

function curationResponse(
  sessionId: string,
  action: SessionMessageCurationAction | null,
): SessionMessageCurationResponse {
  return {
    sessionId,
    captureEnabled: true,
    items: action
      ? [{
        messageId: MESSAGE_ID,
        action,
        modelId: "ai-pixel/gpt-5.6-luna",
        candidateId: "candidate-1",
        decidedAt: "2026-09-26T00:00:00Z",
      }]
      : [],
    countsByModel: [],
  };
}

function mutationResponse(action: SessionMessageCurationAction): SessionMessageCurationMutationResponse {
  return {
    sessionId: "session-a",
    messageId: MESSAGE_ID,
    action,
    status: action === "include" ? "included" : "excluded",
    candidateId: "candidate-1",
    caseId: "case-1",
    modelId: "ai-pixel/gpt-5.6-luna",
    datasetName: "sft",
    summary: "ok",
  };
}

function Harness({
  sessionId,
  companionMode = false,
  onResult,
}: {
  sessionId: string;
  companionMode?: boolean;
  onResult: (result: UseConversationMessageCurationResult) => void;
}) {
  const result = useConversationMessageCuration({
    sessionId,
    companionMode,
    t: (key) => (key === "curationActionFailed" ? "Dataset update failed" : key),
  });
  onResult(result);
  return null;
}

describe("useConversationMessageCuration", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;
  let queryClient: QueryClient | null = null;
  const resultRef: { current: UseConversationMessageCurationResult | null } = { current: null };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    queryClient?.clear();
    root = null;
    container = null;
    queryClient = null;
    resultRef.current = null;
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  async function flush() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }

  async function mount(props: { sessionId: string; companionMode?: boolean }) {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    queryClient?.clear();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const render = (next: { sessionId: string; companionMode?: boolean }) => {
      root?.render(
        <QueryClientProvider client={queryClient!}>
          <Harness
            sessionId={next.sessionId}
            companionMode={next.companionMode}
            onResult={(result) => { resultRef.current = result; }}
          />
        </QueryClientProvider>,
      );
    };
    await act(async () => {
      render(props);
    });
    await flush();
    return { render };
  }

  it("applies an optimistic decision, then yields to the refetched server record", async () => {
    let serverAction: SessionMessageCurationAction = "include";
    vi.mocked(fetchSessionMessageCuration).mockImplementation(async (sessionId: string) => (
      curationResponse(sessionId, serverAction)
    ));
    let resolveSet: (value: SessionMessageCurationMutationResponse) => void = () => undefined;
    vi.mocked(setSessionMessageCuration).mockImplementation(
      () => new Promise<SessionMessageCurationMutationResponse>((resolve) => {
        resolveSet = resolve;
      }),
    );
    await mount({ sessionId: "session-a" });
    const invalidate = vi.spyOn(queryClient!, "invalidateQueries");

    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("include");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.decidedAt).toBe("2026-09-26T00:00:00Z");

    await act(async () => {
      resultRef.current?.handleCurateMessage(MESSAGE_ID, "include");
    });
    expect(setSessionMessageCuration).not.toHaveBeenCalled();

    await act(async () => {
      resultRef.current?.handleCurateMessage(MESSAGE_ID, "exclude");
    });
    expect(setSessionMessageCuration).toHaveBeenCalledTimes(1);
    expect(setSessionMessageCuration).toHaveBeenCalledWith("session-a", MESSAGE_ID, "exclude");
    // The overlay is applied to the override map, so it replaces the server
    // entry until the refetch restores modelId / candidateId / decidedAt.
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("exclude");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.decidedAt).toBe("");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.modelId).toBe("");

    serverAction = "exclude";
    await act(async () => {
      resolveSet(mutationResponse("exclude"));
    });
    await flush();

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["sessions", "session-a", "message-curation"],
    });
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("exclude");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.decidedAt).toBe("2026-09-26T00:00:00Z");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.modelId).toBe("ai-pixel/gpt-5.6-luna");
    expect(resultRef.current?.curationFeedback).toBeNull();
  });

  it("rolls the overlay back and shows 409 copy for about 3s, else the fallback title", async () => {
    vi.mocked(fetchSessionMessageCuration).mockImplementation(async (sessionId: string) => (
      curationResponse(sessionId, "include")
    ));
    vi.mocked(setSessionMessageCuration)
      .mockRejectedValueOnce(new FetchJsonHttpError("已在排除集", { status: 409, code: "conflict" }))
      .mockRejectedValueOnce(new Error("network"));
    await mount({ sessionId: "session-a" });
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("include");

    await act(async () => {
      resultRef.current?.handleCurateMessage(MESSAGE_ID, "exclude");
    });
    await flush();
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("include");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.decidedAt).toBe("2026-09-26T00:00:00Z");
    expect(resultRef.current?.curationFeedback).toEqual({
      messageId: MESSAGE_ID,
      action: "exclude",
      message: "已在排除集",
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2999);
    });
    expect(resultRef.current?.curationFeedback?.message).toBe("已在排除集");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(resultRef.current?.curationFeedback).toBeNull();

    await act(async () => {
      resultRef.current?.handleCurateMessage(MESSAGE_ID, "exclude");
    });
    await flush();
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("include");
    expect(resultRef.current?.curationFeedback).toEqual({
      messageId: MESSAGE_ID,
      action: "exclude",
      message: "Dataset update failed",
    });
  });

  it("drops optimistic overlay and feedback when the session changes", async () => {
    vi.mocked(fetchSessionMessageCuration).mockImplementation(async (sessionId: string) => (
      curationResponse(sessionId, sessionId === "session-a" ? "include" : null)
    ));
    let rejectSet: (error: unknown) => void = () => undefined;
    vi.mocked(setSessionMessageCuration).mockImplementation(
      () => new Promise<SessionMessageCurationMutationResponse>((_resolve, reject) => {
        rejectSet = reject;
      }),
    );
    const { render } = await mount({ sessionId: "session-a" });
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("include");

    await act(async () => {
      resultRef.current?.handleCurateMessage(MESSAGE_ID, "exclude");
    });
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("exclude");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.decidedAt).toBe("");

    await act(async () => {
      rejectSet(new FetchJsonHttpError("冲突", { status: 409, code: "conflict" }));
    });
    await flush();
    expect(resultRef.current?.curationFeedback?.message).toBe("冲突");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("include");

    await act(async () => {
      resultRef.current?.handleCurateMessage(MESSAGE_ID, "exclude");
    });
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("exclude");
    expect(resultRef.current?.curationFeedback?.message).toBe("冲突");

    await act(async () => {
      render({ sessionId: "session-b" });
    });
    await flush();

    expect(resultRef.current?.curationFeedback).toBeNull();
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)).toBeUndefined();
  });

  it("does not fetch when the session id is empty or companion mode is on", async () => {
    vi.mocked(fetchSessionMessageCuration).mockResolvedValue(curationResponse("session-a", "include"));
    await mount({ sessionId: "" });
    await act(async () => {
      resultRef.current?.handleCurateMessage(MESSAGE_ID, "include");
    });
    expect(fetchSessionMessageCuration).not.toHaveBeenCalled();
    expect(setSessionMessageCuration).not.toHaveBeenCalled();

    await mount({ sessionId: "session-a", companionMode: true });
    expect(fetchSessionMessageCuration).not.toHaveBeenCalled();

    await mount({ sessionId: "session-a", companionMode: false });
    expect(fetchSessionMessageCuration).toHaveBeenCalledWith("session-a");
    expect(resultRef.current?.messageCurationMap.get(MESSAGE_ID)?.action).toBe("include");
  });
});
