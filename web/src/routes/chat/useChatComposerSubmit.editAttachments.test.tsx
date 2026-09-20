/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionDetail, SessionReferenceAttachment } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import type { ChatEditTarget } from "../chatComposerState";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import {
  useChatComposerSubmitActions,
  useChatComposerTurnMutations,
} from "./useChatComposerSubmit";

const apiMocks = vi.hoisted(() => ({
  uploadSessionImageAttachment: vi.fn(async (_sessionId: string, _init: unknown) => ({
    artifactId: "artifact-edit-1",
    filename: "sketch.png",
    contentType: "image/png",
    sizeBytes: 5,
  })),
  editResubmitSessionMessage: vi.fn(async (_sessionId: string, _payload: unknown) => ({
    id: "session-1",
    activeTurnId: "accepted-edit-turn",
    currentPhase: "running",
    status: "running",
    messages: [],
    updatedAt: "2026-09-15T02:00:00Z",
  })),
}));

vi.mock("../../api/chat", () => ({
  editResubmitSessionMessage: apiMocks.editResubmitSessionMessage,
  querySessions: vi.fn(),
  regenerateSessionMessage: vi.fn(),
  stopSessionTurn: vi.fn(async () => ({ id: "session-1", currentPhase: "stopping" })),
  submitSessionGuidance: vi.fn(),
  submitSessionMessage: vi.fn(),
  switchSessionHead: vi.fn(),
  uploadSessionImageAttachment: apiMocks.uploadSessionImageAttachment,
}));

vi.mock("./chatSubmitTelemetry", () => ({
  postSubmitTelemetry: vi.fn(),
}));

vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({
    clientOperationId: "test-operation",
    succeeded: () => undefined,
    failed: () => undefined,
    blocked: () => undefined,
  }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const editTarget: ChatEditTarget = {
  messageId: "user-1",
  nodeId: "node-1",
  original: "原始内容",
};

const imageAttachment: ComposerImageAttachment = {
  id: "image-edit-1",
  file: new File(["image"], "sketch.png", { type: "image/png" }),
  filename: "sketch.png",
  previewUrl: "blob:image-edit-1",
  sizeBytes: 5,
  contentType: "image/png",
};

function Harness({ queryClient, sessionBusy = false, activeTurnId = "turn-1" }: {
  queryClient: QueryClient;
  sessionBusy?: boolean;
  activeTurnId?: string;
}) {
  const chatWorkspaceCache = useRef(createChatWorkspaceCache(queryClient)).current;
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({
    "session-1": "编辑后的内容",
  });
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({
    "session-1": [imageAttachment],
  });
  const [sessionReferenceAttachments, setSessionReferenceAttachments] =
    useState<Record<string, SessionReferenceAttachment[]>>({});
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, ChatEditTarget>>({
    "session-1": editTarget,
  });
  const [activeTurnLayersBySession, setActiveTurnLayersBySession] = useState({});
  const detailRef = useRef({
    id: "session-1",
    messages: [{ id: "user-1", role: "user", content: "原始内容" }],
  } as SessionDetail);
  const activeEditTarget = sessionEditTargets["session-1"] ?? null;
  const describeError = (error: unknown, fallback: string) => (
    error instanceof Error ? error.message : fallback
  );

  const mutations = useChatComposerTurnMutations({
    queryClient,
    chatWorkspaceCache,
    t: ((key: TranslationKey) => String(key)) as (key: TranslationKey) => string,
    describeError,
    syncSessionDetail: () => undefined,
    setActiveTurnLayersBySession,
    setSessionDrafts,
    setSessionComposerErrors,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    setSessionEditTargets,
  });

  const actions = useChatComposerSubmitActions({
    ...mutations,
    queryClient,
    lang: "zh",
    describeError,
    setSessionDrafts,
    sessionFollowupQueues: {},
    setSessionFollowupQueues: () => undefined,
    setSessionComposerErrors,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    setSessionImageUploadPending,
    setSessionEditTargets,
    imageUploadInFlightRef,
    activeSessionId: "session-1",
    activeDraftEffective: sessionDrafts["session-1"] ?? "",
    activeImageAttachments: sessionImageAttachments["session-1"] ?? [],
    activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false,
    runtimeStatusEnabledForNextTurn: false,
    resolvedEditTarget: activeEditTarget,
    activeEditTarget,
    composerDisabled: false,
    sessionBusy,
    sessionStopping: false,
    activePhase: "ready",
    activeAgentImageInputUnsupported: false,
    activeImageInputModelId: "model-1",
    activeTurnId,
    detail: detailRef.current,
    setMentalModelEnabledForNextTurn: () => undefined,
    setRuntimeStatusEnabledForNextTurn: () => undefined,
  });

  return (
    <div>
      <output data-testid="images">
        {JSON.stringify((sessionImageAttachments["session-1"] ?? []).map((attachment) => attachment.id))}
      </output>
      <output data-testid="edit-target">
        {JSON.stringify(sessionEditTargets["session-1"] ?? null)}
      </output>
      <output data-testid="draft">{sessionDrafts["session-1"] ?? ""}</output>
      <output data-testid="upload-pending">
        {JSON.stringify(Boolean(sessionImageUploadPending["session-1"]))}
      </output>
      <output data-testid="error">{sessionComposerErrors["session-1"] ?? ""}</output>
      <button type="button" data-testid="submit" onClick={() => actions.handleSubmitTurn()}>
        submit
      </button>
      <button type="button" data-testid="stop" onClick={() => actions.handleStopTurn()}>
        stop
      </button>
    </div>
  );
}

describe("useChatComposerSubmit edit-resubmit attachments", () => {
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
    apiMocks.uploadSessionImageAttachment.mockClear();
    apiMocks.editResubmitSessionMessage.mockClear();
  });

  it("uploads the pending image and sends it with the edited message, then clears the tray", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <Harness queryClient={queryClient} />
        </QueryClientProvider>,
      );
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
    });
    for (let round = 0; round < 6; round += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }

    expect(apiMocks.uploadSessionImageAttachment).toHaveBeenCalledTimes(1);
    expect(apiMocks.uploadSessionImageAttachment.mock.calls[0]?.[0]).toBe("session-1");
    expect(apiMocks.editResubmitSessionMessage).toHaveBeenCalledWith(
      "session-1",
      expect.objectContaining({
        messageId: "user-1",
        baseMessageId: "node-1",
        content: "编辑后的内容",
        attachmentIds: ["artifact-edit-1"],
      }),
    );
    expect(container?.querySelector('[data-testid="images"]')?.textContent).toBe("[]");
    expect(container?.querySelector('[data-testid="edit-target"]')?.textContent).toBe("null");
    expect(container?.querySelector('[data-testid="draft"]')?.textContent).toBe("");
    expect(container?.querySelector('[data-testid="upload-pending"]')?.textContent).toBe("false");
    expect(container?.querySelector('[data-testid="error"]')?.textContent).toBe("");
  });

  it("keeps the stop identity while edit attachments are still uploading", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    let resolveUpload: ((value: { artifactId: string }) => void) | undefined;
    apiMocks.uploadSessionImageAttachment.mockImplementationOnce(() => new Promise((resolve) => {
      resolveUpload = resolve;
    }));
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <Harness queryClient={queryClient} sessionBusy activeTurnId="" />
        </QueryClientProvider>,
      );
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="submit"]')?.click();
      await Promise.resolve();
    });
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="stop"]')?.click();
    });
    expect(apiMocks.editResubmitSessionMessage).not.toHaveBeenCalled();

    await act(async () => {
      resolveUpload?.({ artifactId: "artifact-edit-1" });
      await Promise.resolve();
    });
    for (let round = 0; round < 6; round += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    }

    expect(apiMocks.editResubmitSessionMessage).toHaveBeenCalledTimes(1);
    expect(apiMocks.editResubmitSessionMessage.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      clientSubmissionId: expect.any(String),
    }));
    expect((await import("../../api/chat")).stopSessionTurn).toHaveBeenCalledWith(
      "session-1",
      "accepted-edit-turn",
    );
  });
});
