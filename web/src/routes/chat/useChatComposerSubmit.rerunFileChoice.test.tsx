/** @vitest-environment happy-dom */
import { QueryClient } from "@tanstack/react-query";
import React, { act, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { applySessionTurnRewind, uploadSessionImageAttachment } from "../../api/chat";
import type { ConversationMessage, SessionDetail } from "../../api/types";
import { ConversationRerunFileChoiceDialog } from "../../components/conversation/ConversationRerunFileChoiceDialog";
import type { ChatEditTarget } from "../chatComposerState";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import {
  useChatComposerSubmitActions,
  type ChatComposerTurnMutations,
} from "./useChatComposerSubmit";

const apiMocks = vi.hoisted(() => ({
  applySessionTurnRewind: vi.fn(async () => ({ alreadyApplied: false })),
  uploadSessionImageAttachment: vi.fn(async () => ({ artifactId: "artifact-rerun-1" })),
}));

vi.mock("../../api/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/chat")>();
  return {
    ...actual,
    applySessionTurnRewind: apiMocks.applySessionTurnRewind,
    uploadSessionImageAttachment: apiMocks.uploadSessionImageAttachment,
  };
});

vi.mock("./chatSubmitTelemetry", () => ({
  postSubmitTelemetry: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mutationStub<TVariables>(mutate: (variables: TVariables) => void) {
  return {
    mutate,
    mutateAsync: async (variables: TVariables) => {
      mutate(variables);
      return {};
    },
    isPending: false,
  } as ChatComposerTurnMutations[keyof ChatComposerTurnMutations];
}

function message(
  id: string,
  role: "user" | "assistant",
  extras: { turnId?: string; nodeId?: string; content?: string; paths?: string[] } = {},
): ConversationMessage {
  return {
    id,
    role,
    timestamp: "2026-09-30T00:00:00Z",
    turnId: extras.turnId ?? "",
    status: "completed",
    content: extras.content ?? id,
    nodeId: extras.nodeId,
    metadata: extras.paths
      ? { changedFiles: extras.paths.map((path) => ({ path })) }
      : undefined,
  } as ConversationMessage;
}

const imageAttachment: ComposerImageAttachment = {
  id: "image-rerun-1",
  file: new File(["image"], "sketch.png", { type: "image/png" }),
  filename: "sketch.png",
  previewUrl: "blob:image-rerun-1",
  sizeBytes: 5,
  contentType: "image/png",
};

function Harness({
  messages,
  regenerate,
  edit,
  editTarget = null,
  draft = "",
  images = [],
  regenerateTarget,
}: {
  messages: ConversationMessage[];
  regenerate: (variables: unknown) => void;
  edit: (variables: unknown) => void;
  editTarget?: ChatEditTarget | null;
  draft?: string;
  images?: ComposerImageAttachment[];
  regenerateTarget?: ConversationMessage;
}) {
  const queryClient = useRef(new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })).current;
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const [sessionId, setSessionId] = useState("session-1");
  const actions = useChatComposerSubmitActions({
    queryClient,
    lang: "zh",
    describeError: (error, fallback) => (error instanceof Error ? error.message : fallback),
    submitTurnMutation: mutationStub(vi.fn()),
    editResubmitMutation: mutationStub(edit),
    regenerateMutation: mutationStub(regenerate),
    stopTurnMutation: mutationStub(vi.fn()),
    sessionGuidanceMutation: mutationStub(vi.fn()),
    setSessionDrafts: () => undefined,
    sessionFollowupQueues: {},
    setSessionFollowupQueues: () => undefined,
    setSessionComposerErrors: () => undefined,
    setSessionImageAttachments: () => undefined,
    setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined,
    setSessionEditTargets: () => undefined,
    imageUploadInFlightRef,
    activeSessionId: sessionId,
    activeDraftEffective: draft,
    activeImageAttachments: images,
    activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false,
    runtimeStatusEnabledForNextTurn: false,
    resolvedEditTarget: editTarget,
    activeEditTarget: editTarget,
    composerDisabled: false,
    sessionBusy: false,
    sessionStopping: false,
    activePhase: "ready",
    activeAgentImageInputUnsupported: false,
    activeImageInputModelId: "model-1",
    latestUserMessageId: "user-1",
    activeTurnId: "turn-b",
    detail: { id: sessionId, activeTurnId: "turn-b", messages } as SessionDetail,
    setMentalModelEnabledForNextTurn: () => undefined,
    setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  const choice = actions.rerunFileChoice;

  return (
    <>
      <button type="button" data-testid="retry" onClick={() => actions.handleRetryFailedTurn()}>
        retry
      </button>
      <button
        type="button"
        data-testid="regenerate-message"
        onClick={() => {
          if (regenerateTarget) actions.handleRegenerateAssistantMessage(regenerateTarget);
        }}
      >
        regenerate
      </button>
      <button type="button" data-testid="submit" onClick={() => actions.handleSubmitTurn()}>
        submit
      </button>
      <button type="button" data-testid="switch-session" onClick={() => setSessionId("session-2")}>
        switch
      </button>
      <ConversationRerunFileChoiceDialog
        open={Boolean(choice)}
        language="zh"
        paths={choice?.paths ?? []}
        pending={Boolean(choice?.restoring)}
        error={choice?.error ?? ""}
        onOpenChange={(open) => {
          if (!open) actions.dismissRerunFileChoice();
        }}
        onRestoreAndRerun={() => {
          void actions.confirmRerunFileRestore();
        }}
        onRerunOnly={actions.keepFilesAndRerun}
      />
    </>
  );
}

function buttonByText(text: string): HTMLButtonElement | null {
  return Array.from(document.querySelectorAll("button"))
    .find((button) => (button.textContent ?? "").includes(text)) ?? null;
}

async function clickTestId(id: string) {
  await act(async () => {
    document.querySelector<HTMLButtonElement>(`[data-testid="${id}"]`)?.click();
  });
}

async function clickLabel(text: string) {
  await act(async () => {
    buttonByText(text)?.click();
  });
}

async function settle() {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

describe("useChatComposerSubmitActions rerun file choice", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    document.body.innerHTML = "";
    root = null;
    apiMocks.applySessionTurnRewind.mockReset();
    apiMocks.applySessionTurnRewind.mockResolvedValue({ alreadyApplied: false });
    apiMocks.uploadSessionImageAttachment.mockClear();
  });

  const changedTail = [
    message("user-1", "user", { turnId: "turn-user", nodeId: "node-user-1", content: "请改登录" }),
    message("assistant-a", "assistant", { turnId: "turn-a", nodeId: "node-a", paths: ["src/a.ts"] }),
    message("assistant-b", "assistant", { turnId: "turn-b", nodeId: "node-b", paths: ["src/b.ts"] }),
  ];

  async function mount(props: Partial<React.ComponentProps<typeof Harness>> & {
    regenerate?: (variables: unknown) => void;
    edit?: (variables: unknown) => void;
  } = {}) {
    const regenerate = props.regenerate ?? vi.fn();
    const edit = props.edit ?? vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <Harness
          messages={props.messages ?? changedTail}
          regenerate={regenerate}
          edit={edit}
          editTarget={props.editTarget}
          draft={props.draft}
          images={props.images}
          regenerateTarget={props.regenerateTarget}
        />,
      );
    });
    return { regenerate, edit };
  }

  it("retries immediately when the tail has no changed files", async () => {
    const { regenerate } = await mount({
      messages: [message("user-1", "user", { turnId: "turn-1", nodeId: "node-user-1", content: "请修复" })],
    });

    await clickTestId("retry");

    expect(regenerate).toHaveBeenCalledTimes(1);
    expect(document.body.textContent ?? "").not.toContain("重跑前要不要还原文件？");
    expect(applySessionTurnRewind).not.toHaveBeenCalled();
  });

  it("asks before retry, then reruns without restoring when that choice is clicked", async () => {
    const { regenerate } = await mount();

    await clickTestId("retry");
    await clickTestId("retry");

    expect(regenerate).not.toHaveBeenCalled();
    expect(document.body.textContent ?? "").toContain("src/a.ts");
    expect(document.body.textContent ?? "").toContain("src/b.ts");

    await clickLabel("只重跑");

    expect(applySessionTurnRewind).not.toHaveBeenCalled();
    expect(regenerate).toHaveBeenCalledTimes(1);
    expect(regenerate).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "session-1",
      messageId: "user-1",
      baseMessageId: "node-user-1",
    }));
  });

  it("restores newer turns first and only then reruns", async () => {
    const { regenerate } = await mount();

    await clickTestId("retry");
    await clickLabel("还原文件并重跑");
    await settle();

    expect(applySessionTurnRewind).toHaveBeenNthCalledWith(1, "session-1", { turnId: "turn-b", force: false });
    expect(applySessionTurnRewind).toHaveBeenNthCalledWith(2, "session-1", { turnId: "turn-a", force: false });
    expect(regenerate).toHaveBeenCalledTimes(1);
  });

  it("keeps the dialog open and does not rerun when a restore is rejected", async () => {
    apiMocks.applySessionTurnRewind.mockImplementation(async (_sessionId: string, payload: { turnId: string }) => {
      if (payload.turnId === "turn-a") {
        throw new Error("文件已被其他程序修改");
      }
      return { alreadyApplied: false };
    });
    const { regenerate } = await mount();

    await clickTestId("retry");
    await clickLabel("还原文件并重跑");
    await settle();

    expect(regenerate).not.toHaveBeenCalled();
    expect(document.body.textContent ?? "").toContain("文件已被其他程序修改");
    expect(document.body.textContent ?? "").toContain("重跑前要不要还原文件？");
    expect(buttonByText("只重跑")?.disabled).toBe(false);
  });

  it("drops the question without rerunning when the session changes or the choice is cancelled", async () => {
    const { regenerate } = await mount();

    await clickTestId("retry");
    await clickTestId("switch-session");

    expect(regenerate).not.toHaveBeenCalled();
    expect(document.body.textContent ?? "").not.toContain("重跑前要不要还原文件？");
  });

  it("cancels an edit without uploading or resubmitting", async () => {
    const { edit } = await mount({
      editTarget: { messageId: "user-1", nodeId: "node-user-1", original: "请改登录" },
      draft: "改过的登录问题",
      images: [imageAttachment],
    });

    await clickTestId("submit");

    expect(edit).not.toHaveBeenCalled();
    expect(uploadSessionImageAttachment).not.toHaveBeenCalled();

    await clickLabel("取消");

    expect(edit).not.toHaveBeenCalled();
    expect(uploadSessionImageAttachment).not.toHaveBeenCalled();
    expect(document.body.textContent ?? "").not.toContain("重跑前要不要还原文件？");
  });

  it("uploads the edit attachment only after the rerun choice", async () => {
    const { edit } = await mount({
      editTarget: { messageId: "user-1", nodeId: "node-user-1", original: "请改登录" },
      draft: "改过的登录问题",
      images: [imageAttachment],
    });

    await clickTestId("submit");
    expect(uploadSessionImageAttachment).not.toHaveBeenCalled();

    await clickLabel("只重跑");
    await settle();

    expect(uploadSessionImageAttachment).toHaveBeenCalledTimes(1);
    expect(edit).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "session-1",
      messageId: "user-1",
      content: "改过的登录问题",
      attachmentIds: ["artifact-rerun-1"],
    }));
  });

  it("asks regenerate only about files from the clicked answer onward", async () => {
    const { regenerate } = await mount({
      regenerateTarget: changedTail[2],
    });

    await clickTestId("regenerate-message");

    expect(regenerate).not.toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("src/b.ts");
    expect(body).not.toContain("src/a.ts");

    await clickLabel("只重跑");
    expect(regenerate).toHaveBeenCalledWith(expect.objectContaining({
      messageId: "user-1",
      baseMessageId: "node-b",
    }));
  });
});
