/** @vitest-environment happy-dom */
import { QueryClient } from "@tanstack/react-query";
import React, { act, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionDetail } from "../../api/types";
import {
  useChatComposerSubmitActions,
  type ChatComposerTurnMutations,
} from "./useChatComposerSubmit";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";

vi.mock("./chatSubmitTelemetry", () => ({
  postSubmitTelemetry: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type HarnessProps = {
  sessionId?: string;
  busy: boolean;
  draft: string;
  queues: Record<string, ComposerQueueItem[]>;
  imageAttachments?: ComposerImageAttachment[];
  mutations: ChatComposerTurnMutations;
  onQueues: (queues: Record<string, ComposerQueueItem[]>) => void;
  onDrafts?: (drafts: Record<string, string>) => void;
  onErrors?: (errors: Record<string, string>) => void;
};

function mutationStub<TVariables>(
  mutate: (variables: TVariables) => void,
  mutateAsync?: (variables: TVariables) => Promise<unknown>,
) {
  return {
    mutate,
    mutateAsync: mutateAsync ?? (async (variables: TVariables) => {
      mutate(variables);
      return {};
    }),
    isPending: false,
  } as ChatComposerTurnMutations[keyof ChatComposerTurnMutations];
}

function Harness({
  sessionId = "session-1",
  busy,
  draft,
  queues,
  imageAttachments = [],
  mutations,
  onQueues,
  onDrafts,
  onErrors,
}: HarnessProps) {
  const queryClient = useRef(new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })).current;
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({
    [sessionId]: draft,
  });
  const [sessionFollowupQueues, setSessionFollowupQueues] = useState(queues);
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const actions = useChatComposerSubmitActions({
    queryClient,
    lang: "zh",
    describeError: (error, fallback) => (error instanceof Error ? error.message : fallback),
    submitTurnMutation: mutations.submitTurnMutation,
    editResubmitMutation: mutations.editResubmitMutation,
    stopTurnMutation: mutations.stopTurnMutation,
    sessionGuidanceMutation: mutations.sessionGuidanceMutation,
    setSessionDrafts: (value) => {
      setSessionDrafts(value);
      if (typeof value !== "function") {
        onDrafts?.(value);
      }
    },
    sessionFollowupQueues,
    setSessionFollowupQueues: (value) => {
      setSessionFollowupQueues((current) => {
        const next = typeof value === "function" ? value(current) : value;
        onQueues(next);
        return next;
      });
    },
    setSessionComposerErrors: (value) => {
      if (typeof value === "function") {
        onErrors?.(value({}));
      } else {
        onErrors?.(value);
      }
    },
    setSessionImageAttachments: () => undefined,
    setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined,
    setSessionEditTargets: () => undefined,
    imageUploadInFlightRef,
    activeSessionId: sessionId,
    activeDraftEffective: draft,
    activeImageAttachments: imageAttachments,
    activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false,
    runtimeStatusEnabledForNextTurn: false,
    resolvedEditTarget: null,
    activeEditTarget: null,
    composerDisabled: false,
    sessionBusy: busy,
    sessionStopping: false,
    activePhase: busy ? "running" : "ready",
    activeAgentImageInputUnsupported: false,
    activeImageInputModelId: "model-1",
    latestUserMessageId: "user-1",
    activeTurnId: `turn-${sessionId}`,
    detail: { id: sessionId, activeTurnId: `turn-${sessionId}` } as SessionDetail,
    setMentalModelEnabledForNextTurn: () => undefined,
    setRuntimeStatusEnabledForNextTurn: () => undefined,
  });

  return (
    <div>
      <output data-testid="draft">{sessionDrafts[sessionId] ?? ""}</output>
      <output data-testid="queue">{JSON.stringify(sessionFollowupQueues[sessionId] ?? [])}</output>
      <button type="button" data-testid="submit" onClick={() => actions.handleSubmitTurn()}>submit</button>
      <button type="button" data-testid="stop" onClick={() => actions.handleStopTurn()}>stop</button>
      <button
        type="button"
        data-testid="append-queue"
        onClick={() => {
          setSessionFollowupQueues((current) => {
            const next = {
              ...current,
              [sessionId]: [
                ...(current[sessionId] ?? []),
                { id: `q-new-${sessionId}`, text: `new-${sessionId}` },
              ],
            };
            onQueues(next);
            return next;
          });
        }}
      >
        append
      </button>
    </div>
  );
}

describe("useChatComposerSubmitActions follow-up queue", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  function createMutations() {
    const submitTurn = vi.fn();
    const stopTurn = vi.fn();
    const guidance = vi.fn();
    return {
      submitTurn,
      stopTurn,
      guidance,
      mutations: {
        submitTurnMutation: mutationStub(submitTurn),
        editResubmitMutation: mutationStub(vi.fn()),
        stopTurnMutation: mutationStub(stopTurn),
        sessionGuidanceMutation: mutationStub(guidance, async (variables) => {
          guidance(variables);
          return {};
        }),
      } as ChatComposerTurnMutations,
    };
  }

  async function mount(props: Omit<HarnessProps, "onQueues"> & { onQueues?: HarnessProps["onQueues"] }) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const onQueues = props.onQueues ?? vi.fn();
    await act(async () => {
      root?.render(<Harness {...props} onQueues={onQueues} />);
    });
    return { onQueues };
  }

  it("enqueues typed follow-ups while the turn is running", async () => {
    const { mutations, submitTurn, guidance } = createMutations();
    let queues: Record<string, ComposerQueueItem[]> = {};
    await mount({
      busy: true,
      draft: "先不要改测试，只汇报改了哪些文件。",
      queues: {},
      mutations,
      onQueues: (next) => {
        queues = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
    });

    expect(queues["session-1"]?.map((item) => item.text)).toEqual([
      "先不要改测试，只汇报改了哪些文件。",
    ]);
    expect(submitTurn).not.toHaveBeenCalled();
    expect(guidance).not.toHaveBeenCalled();
  });

  it("rejects text-only queueing while an image attachment is present", async () => {
    const { mutations, submitTurn, guidance } = createMutations();
    let queues: Record<string, ComposerQueueItem[]> = {};
    let errors: Record<string, string> = {};
    await mount({
      busy: true,
      draft: "describe this image",
      queues,
      imageAttachments: [{
        id: "image-1",
        file: new File(["image"], "image.png", { type: "image/png" }),
        filename: "image.png",
        previewUrl: "blob:image-1",
        sizeBytes: 5,
        contentType: "image/png",
      }],
      mutations,
      onQueues: (next) => {
        queues = next;
      },
      onErrors: (next) => {
        errors = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
    });

    expect(queues["session-1"]).toBeUndefined();
    expect(errors["session-1"]).toContain("仅支持文本");
    expect(submitTurn).not.toHaveBeenCalled();
    expect(guidance).not.toHaveBeenCalled();
  });

  it("sends each queued item as safe guidance on immediate steer", async () => {
    const { mutations, guidance } = createMutations();
    let queues: Record<string, ComposerQueueItem[]> = {
      "session-1": [
        { id: "q-1", text: "先不要改测试" },
        { id: "q-2", text: "登录失败用中文提示" },
      ],
    };
    await mount({
      busy: true,
      draft: "",
      queues,
      mutations,
      onQueues: (next) => {
        queues = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(guidance).toHaveBeenCalledTimes(2);
    expect(guidance).toHaveBeenNthCalledWith(1, {
      sessionId: "session-1",
      content: "先不要改测试",
      mode: "safe",
    });
    expect(guidance).toHaveBeenNthCalledWith(2, {
      sessionId: "session-1",
      content: "登录失败用中文提示",
      mode: "safe",
    });
    expect(queues["session-1"]).toEqual([]);
    expect(mutations.submitTurnMutation.mutate).not.toHaveBeenCalled();
  });

  it("auto-sends only the first queued item when the current turn ends", async () => {
    const { mutations, submitTurn } = createMutations();
    let queues: Record<string, ComposerQueueItem[]> = {
      "session-1": [
        { id: "q-1", text: "先不要改测试" },
        { id: "q-2", text: "登录失败用中文提示" },
      ],
    };
    await mount({
      busy: true,
      draft: "",
      queues,
      mutations,
      onQueues: (next) => {
        queues = next;
      },
    });

    await act(async () => {
      root?.render(
        <Harness
          busy={false}
          draft=""
          queues={queues}
          mutations={mutations}
          onQueues={(next) => {
            queues = next;
          }}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(submitTurn).toHaveBeenCalledTimes(1);
    expect(submitTurn.mock.calls[0]?.[0]).toMatchObject({
      sessionId: "session-1",
      content: "先不要改测试",
    });
    expect(queues["session-1"]?.map((item) => item.text)).toEqual(["登录失败用中文提示"]);
  });

  it("keeps the queue after stop and does not auto-send", async () => {
    const { mutations, submitTurn, stopTurn } = createMutations();
    let queues: Record<string, ComposerQueueItem[]> = {
      "session-1": [{ id: "q-1", text: "先不要改测试" }],
    };
    await mount({
      busy: true,
      draft: "",
      queues,
      mutations,
      onQueues: (next) => {
        queues = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="stop"]')?.click();
    });
    expect(stopTurn).toHaveBeenCalledWith({
      sessionId: "session-1",
      turnId: "turn-session-1",
    });

    await act(async () => {
      root?.render(
        <Harness
          busy={false}
          draft=""
          queues={queues}
          mutations={mutations}
          onQueues={(next) => {
            queues = next;
          }}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(submitTurn).not.toHaveBeenCalled();
    expect(queues["session-1"]?.map((item) => item.text)).toEqual(["先不要改测试"]);
  });

  it("preserves concurrently appended items when immediate steer partially fails", async () => {
    const guidance = vi.fn();
    let rejectSecond: ((reason?: unknown) => void) | undefined;
    let callCount = 0;
    const mutations = {
      submitTurnMutation: mutationStub(vi.fn()),
      editResubmitMutation: mutationStub(vi.fn()),
      stopTurnMutation: mutationStub(vi.fn()),
      sessionGuidanceMutation: mutationStub(guidance, async (variables) => {
        guidance(variables);
        callCount += 1;
        if (callCount === 2) {
          await new Promise<never>((_resolve, reject) => {
            rejectSecond = reject;
          });
        }
        return {};
      }),
    } as ChatComposerTurnMutations;
    let queues: Record<string, ComposerQueueItem[]> = {
      "session-1": [
        { id: "q-1", text: "first" },
        { id: "q-2", text: "second" },
      ],
    };
    await mount({
      busy: true,
      draft: "",
      queues,
      mutations,
      onQueues: (next) => {
        queues = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
      await Promise.resolve();
    });
    expect(guidance).toHaveBeenCalledTimes(2);

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="append-queue"]')?.click();
    });
    await act(async () => {
      rejectSecond?.(new Error("guidance failed"));
      await Promise.resolve();
    });

    expect(queues["session-1"]?.map((item) => item.id)).toEqual([
      "q-2",
      "q-new-session-1",
    ]);
  });

  it("does not apply one session stop suppression to another session", async () => {
    const { mutations, submitTurn, stopTurn } = createMutations();
    let queues: Record<string, ComposerQueueItem[]> = {
      "session-1": [{ id: "q-1", text: "keep after stop" }],
      "session-2": [{ id: "q-2", text: "send after completion" }],
    };
    await mount({
      sessionId: "session-1",
      busy: true,
      draft: "",
      queues,
      mutations,
      onQueues: (next) => {
        queues = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="stop"]')?.click();
    });
    expect(stopTurn).toHaveBeenCalledTimes(1);

    await act(async () => {
      root?.render(
        <Harness
          sessionId="session-2"
          busy
          draft=""
          queues={queues}
          mutations={mutations}
          onQueues={(next) => {
            queues = next;
          }}
        />,
      );
    });
    await act(async () => {
      root?.render(
        <Harness
          sessionId="session-2"
          busy={false}
          draft=""
          queues={queues}
          mutations={mutations}
          onQueues={(next) => {
            queues = next;
          }}
        />,
      );
      await Promise.resolve();
    });

    expect(submitTurn).toHaveBeenCalledTimes(1);
    expect(submitTurn.mock.calls[0]?.[0]).toMatchObject({
      sessionId: "session-2",
      content: "send after completion",
    });
    expect(queues["session-1"]?.map((item) => item.id)).toEqual(["q-1"]);
  });
});
