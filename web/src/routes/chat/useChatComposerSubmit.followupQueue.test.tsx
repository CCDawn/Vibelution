/** @vitest-environment happy-dom */
import { QueryClient } from "@tanstack/react-query";
import React, { act, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionDetail } from "../../api/types";
import {
  removeSessionQueuedTurn,
  updateSessionQueuedTurn,
} from "../../api/chat";
import {
  useChatComposerSubmitActions,
  type ChatComposerTurnMutations,
} from "./useChatComposerSubmit";
import type { ComposerQueueItem } from "../../components/conversation/composerFollowupQueueModel";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";

vi.mock("./chatSubmitTelemetry", () => ({
  postSubmitTelemetry: vi.fn(),
}));

vi.mock("../../api/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/chat")>();
  return {
    ...actual,
    listSessionQueuedTurns: vi.fn(async () => []),
    removeSessionQueuedTurn: vi.fn(async () => []),
    updateSessionQueuedTurn: vi.fn(async () => []),
    uploadSessionImageAttachment: vi.fn(async () => ({ artifactId: "artifact-1" })),
  };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type HarnessProps = {
  sessionId?: string;
  companionAgentId?: string;
  busy: boolean;
  stopping?: boolean;
  draft: string;
  queues: Record<string, ComposerQueueItem[]>;
  imageAttachments?: ComposerImageAttachment[];
  mutations: ChatComposerTurnMutations;
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
  companionAgentId,
  busy,
  stopping,
  draft,
  queues,
  imageAttachments = [],
  mutations,
  onErrors,
}: HarnessProps) {
  const queryClient = useRef(new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })).current;
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({
    [sessionId]: draft,
  });
  const [sessionFollowupQueues] = useState(queues);
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({
    [sessionId]: imageAttachments,
  });
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const actions = useChatComposerSubmitActions({
    queryClient,
    lang: "zh",
    describeError: (error, fallback) => (error instanceof Error ? error.message : fallback),
    submitTurnMutation: mutations.submitTurnMutation,
    editResubmitMutation: mutations.editResubmitMutation,
    regenerateMutation: mutations.regenerateMutation,
    stopTurnMutation: mutations.stopTurnMutation,
    sessionGuidanceMutation: mutations.sessionGuidanceMutation,
    setSessionDrafts,
    sessionFollowupQueues,
    setSessionComposerErrors: (value) => {
      if (typeof value === "function") {
        onErrors?.(value({}));
      } else {
        onErrors?.(value);
      }
    },
    setSessionImageAttachments,
    setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined,
    setSessionEditTargets: () => undefined,
    imageUploadInFlightRef,
    activeSessionId: sessionId,
    activeDraftEffective: draft,
    activeImageAttachments: sessionImageAttachments[sessionId] ?? [],
    activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false,
    runtimeStatusEnabledForNextTurn: false,
    resolvedEditTarget: null,
    activeEditTarget: null,
    composerDisabled: false,
    sessionBusy: busy,
    sessionStopping: stopping ?? false,
    activePhase: busy ? "running" : "ready",
    activeAgentImageInputUnsupported: false,
    activeImageInputModelId: "model-1",
    latestUserMessageId: "user-1",
    activeTurnId: `turn-${sessionId}`,
    detail: {
      id: sessionId,
      activeTurnId: `turn-${sessionId}`,
      queuedTurns: queues[sessionId] ?? [],
    } as SessionDetail,
    setMentalModelEnabledForNextTurn: () => undefined,
    setRuntimeStatusEnabledForNextTurn: () => undefined,
    companionAgentId,
  });

  return (
    <div>
      <output data-testid="draft">{sessionDrafts[sessionId] ?? ""}</output>
      <button type="button" data-testid="submit" onClick={() => actions.handleSubmitTurn()}>submit</button>
      <button type="button" data-testid="stop" onClick={() => actions.handleStopTurn()}>stop</button>
      <button
        type="button"
        data-testid="add-image"
        onClick={() => actions.handleAddComposerAttachments([new File(["image"], "image.png", { type: "image/png" })])}
      >
        add-image
      </button>
      <output data-testid="images">{JSON.stringify((sessionImageAttachments[sessionId] ?? []).map((item) => item.filename))}</output>
      <button type="button" data-testid="remove-image" onClick={() => {
        const first = sessionImageAttachments[sessionId]?.[0];
        if (first) actions.handleRemoveComposerAttachment(first.id);
      }}>remove image</button>
      <button
        type="button"
        data-testid="add-reference"
        onClick={() => actions.handleAddComposerReference({ kind: "session", sessionId: "session-ref-1" })}
      >
        add-reference
      </button>
      <button
        type="button"
        data-testid="update-queue"
        onClick={() => actions.handleFollowupQueueUpdate("q-1", "改后的排队文本")}
      >
        update
      </button>
      <button
        type="button"
        data-testid="remove-queue"
        onClick={() => actions.handleFollowupQueueRemove("q-1")}
      >
        remove
      </button>
      <button
        type="button"
        data-testid="move-queue"
        onClick={() => actions.handleFollowupQueueMove(0, 1)}
      >
        move
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
    vi.clearAllMocks();
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
        regenerateMutation: mutationStub(vi.fn()),
        stopTurnMutation: mutationStub(stopTurn),
        sessionGuidanceMutation: mutationStub(guidance, async (variables) => {
          guidance(variables);
          return {};
        }),
      } as ChatComposerTurnMutations,
    };
  }

  async function mount(props: HarnessProps) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness {...props} />);
    });
  }

  it("queues the typed follow-up on the server while the turn is running", async () => {
    const { mutations, submitTurn, guidance } = createMutations();
    await mount({
      busy: true,
      draft: "先不要改测试，只汇报改了哪些文件。",
      queues: {},
      mutations,
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
    });

    expect(submitTurn).toHaveBeenCalledTimes(1);
    expect(submitTurn.mock.calls[0]?.[0]).toMatchObject({
      sessionId: "session-1",
      content: "先不要改测试，只汇报改了哪些文件。",
      queuedBehindActiveTurn: true,
    });
    expect(guidance).not.toHaveBeenCalled();
  });

  it("queues images and references with the follow-up instead of rejecting them", async () => {
    const { mutations, submitTurn } = createMutations();
    let errors: Record<string, string> = {};
    await mount({
      busy: true,
      draft: "describe this image",
      queues: {},
      imageAttachments: [{
        id: "image-1",
        file: new File(["image"], "image.png", { type: "image/png" }),
        filename: "image.png",
        previewUrl: "blob:image-1",
        sizeBytes: 5,
        contentType: "image/png",
      }],
      mutations,
      onErrors: (next) => {
        errors = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(submitTurn).toHaveBeenCalledTimes(1);
    expect(submitTurn.mock.calls[0]?.[0]).toMatchObject({
      sessionId: "session-1",
      content: "describe this image",
      queuedBehindActiveTurn: true,
      attachmentIds: ["artifact-1"],
    });
    expect(errors["session-1"] ?? "").not.toContain("仅支持文本");
  });

  it("accepts images added while the turn is still running", async () => {
    const { mutations } = createMutations();
    let errors: Record<string, string> = {};
    await mount({
      busy: true,
      draft: "",
      queues: {},
      mutations,
      onErrors: (next) => {
        errors = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="add-image"]')?.click();
    });

    expect(errors["session-1"] ?? "").toBe("");
  });

  it("keeps both attachments when add is invoked twice in one act", async () => {
    const { mutations } = createMutations();
    await mount({ busy: true, draft: "", queues: {}, mutations });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="add-image"]')?.click();
      container?.querySelector<HTMLButtonElement>('[data-testid="add-image"]')?.click();
    });

    expect(JSON.parse(container?.querySelector<HTMLOutputElement>('[data-testid="images"]')?.textContent ?? "[]")).toHaveLength(2);
  });

  it("does not restore a removed attachment when adding again in the same act", async () => {
    const { mutations } = createMutations();
    await mount({ busy: true, draft: "", queues: {}, mutations });
    await act(async () => container?.querySelector<HTMLButtonElement>('[data-testid="add-image"]')?.click());
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="remove-image"]')?.click();
      container?.querySelector<HTMLButtonElement>('[data-testid="add-image"]')?.click();
    });
    expect(JSON.parse(container?.querySelector<HTMLOutputElement>('[data-testid="images"]')?.textContent ?? "[]")).toHaveLength(1);
  });

  it("accepts references added while the turn is still running", async () => {
    const { mutations } = createMutations();
    let errors: Record<string, string> = {};
    await mount({
      busy: true,
      draft: "",
      queues: {},
      mutations,
      onErrors: (next) => {
        errors = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="add-reference"]')?.click();
    });

    expect(errors["session-1"] ?? "").toBe("");
  });

  it("submits busy Companion text to the plugin mailbox without changing the ordinary follow-up queue", async () => {
    const { mutations, submitTurn, guidance } = createMutations();
    await mount({
      companionAgentId: "agent-companion",
      busy: true,
      draft: "你先忙，我也可以继续发消息。",
      queues: {},
      mutations,
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
    });

    expect(submitTurn).toHaveBeenCalledTimes(1);
    expect(submitTurn).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "session-1",
      content: "你先忙，我也可以继续发消息。",
      queuedBehindActiveTurn: true,
    }));
    expect(guidance).not.toHaveBeenCalled();
  });

  it("keeps the busy Companion path text-only", async () => {
    const { mutations, submitTurn } = createMutations();
    let errors: Record<string, string> = {};
    await mount({
      companionAgentId: "agent-companion",
      busy: true,
      draft: "带图你也先处理着",
      queues: {},
      imageAttachments: [{
        id: "image-1",
        file: new File(["image"], "image.png", { type: "image/png" }),
        filename: "image.png",
        previewUrl: "blob:image-1",
        sizeBytes: 5,
        contentType: "image/png",
      }],
      mutations,
      onErrors: (next) => {
        errors = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
    });

    expect(errors["session-1"]).toContain("只能继续发送文字");
    expect(submitTurn).not.toHaveBeenCalled();
  });

  it("steers the first queued item on an empty submit", async () => {
    const { mutations, guidance } = createMutations();
    await mount({
      busy: true,
      draft: "",
      queues: {
        "session-1": [
          { id: "q-1", text: "先不要改测试" },
          { id: "q-2", text: "登录失败用中文提示" },
        ],
      },
      mutations,
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(guidance).toHaveBeenCalledTimes(1);
    expect(guidance).toHaveBeenCalledWith({
      sessionId: "session-1",
      content: "先不要改测试",
      mode: "safe",
    });
    expect(removeSessionQueuedTurn).toHaveBeenCalledWith("session-1", "q-1");
    expect(mutations.submitTurnMutation.mutate).not.toHaveBeenCalled();
  });

  it("refuses to steer a queued item that carries attachments", async () => {
    const { mutations, guidance } = createMutations();
    let errors: Record<string, string> = {};
    await mount({
      busy: true,
      draft: "",
      queues: {
        "session-1": [{ id: "q-1", text: "带图的排队消息", canSteer: false }],
      },
      mutations,
      onErrors: (next) => {
        errors = next;
      },
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
    });

    expect(errors["session-1"]).toContain("无法立即引导");
    expect(guidance).not.toHaveBeenCalled();
    expect(removeSessionQueuedTurn).not.toHaveBeenCalled();
  });

  it("updates, withdraws and reorders queued turns through the server", async () => {
    const { mutations } = createMutations();
    await mount({
      busy: true,
      draft: "",
      queues: {
        "session-1": [
          { id: "q-1", text: "第一条", position: 1 },
          { id: "q-2", text: "第二条", position: 2 },
        ],
      },
      mutations,
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="update-queue"]')?.click();
      container?.querySelector<HTMLButtonElement>('[data-testid="remove-queue"]')?.click();
      container?.querySelector<HTMLButtonElement>('[data-testid="move-queue"]')?.click();
    });

    expect(updateSessionQueuedTurn).toHaveBeenCalledWith("session-1", "q-1", { content: "改后的排队文本" });
    expect(removeSessionQueuedTurn).toHaveBeenCalledWith("session-1", "q-1");
    expect(updateSessionQueuedTurn).toHaveBeenCalledWith("session-1", "q-1", { position: 2 });
  });

  it("no longer flushes the queue locally when the turn ends", async () => {
    const { mutations, submitTurn } = createMutations();
    await mount({
      busy: true,
      draft: "",
      queues: {
        "session-1": [{ id: "q-1", text: "先不要改测试" }],
      },
      mutations,
    });

    await act(async () => {
      root?.render(
        <Harness
          busy={false}
          draft=""
          queues={{ "session-1": [{ id: "q-1", text: "先不要改测试" }] }}
          mutations={mutations}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(submitTurn).not.toHaveBeenCalled();
  });
});
