// @vitest-environment happy-dom
import React, { act, useCallback, useRef, useState } from "react";
import { QueryClient } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionReferenceAttachment } from "../../api/types";
import type { ChatEditTarget } from "../chatComposerState";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import {
  useChatComposerSubmitActions,
  type ChatComposerTurnMutations,
  type UseChatComposerSubmitActionsResult,
} from "./useChatComposerSubmit";

const apiMocks = vi.hoisted(() => ({
  uploadSessionImageAttachment: vi.fn(),
}));

vi.mock("../../api/chat", () => ({
  uploadSessionImageAttachment: apiMocks.uploadSessionImageAttachment,
}));
vi.mock("../../api/desktopPlatform", () => ({ resolveLocalFilePath: () => null }));
vi.mock("./chatSubmitTelemetry", () => ({ postSubmitTelemetry: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({
    succeeded: () => undefined,
    failed: () => undefined,
    blocked: () => undefined,
  }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type HarnessProps = {
  queryClient: QueryClient;
  mutations: ChatComposerTurnMutations;
  initialAttachments: Record<string, ComposerImageAttachment[]>;
  actionsRef?: { current: UseChatComposerSubmitActionsResult | null };
  imageSetterCallsRef?: { current: number };
  unsupportedImages?: boolean;
};

function makeMutation() {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
    isSuccess: false,
    variables: undefined,
    data: undefined,
    error: null,
  };
}

function makeMutations(): ChatComposerTurnMutations {
  return {
    submitTurnMutation: makeMutation(),
    editResubmitMutation: makeMutation(),
    regenerateMutation: makeMutation(),
    switchHeadMutation: makeMutation(),
    stopTurnMutation: makeMutation(),
    sessionGuidanceMutation: makeMutation(),
  } as unknown as ChatComposerTurnMutations;
}

function makeAttachment(id: string, previewUrl: string): ComposerImageAttachment {
  const file = new File([id], `${id}.png`, { type: "image/png" });
  return {
    id,
    file,
    filename: file.name,
    previewUrl,
    sizeBytes: file.size,
    contentType: file.type,
    kind: "image",
  };
}

function Harness({
  queryClient,
  mutations,
  initialAttachments,
  actionsRef,
  imageSetterCallsRef,
  unsupportedImages = false,
}: HarnessProps) {
  const [activeSessionId, setActiveSessionId] = useState("session-a");
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({
    "session-a": "带附件发送",
  });
  const [sessionImageAttachmentsBySession, setSessionImageAttachmentsState] = useState(initialAttachments);
  const [sessionReferenceAttachments, setSessionReferenceAttachments] =
    useState<Record<string, SessionReferenceAttachment[]>>({});
  const [sessionImageUploadPending, setSessionImageUploadPending] = useState<Record<string, boolean>>({});
  const [sessionComposerErrors, setSessionComposerErrors] = useState<Record<string, string>>({});
  const [sessionEditTargets, setSessionEditTargets] = useState<Record<string, ChatEditTarget>>({});
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const sessionImageAttachments = sessionImageAttachmentsBySession[activeSessionId] ?? [];
  const setSessionImageAttachments = useCallback((next: React.SetStateAction<Record<string, ComposerImageAttachment[]>>) => {
    if (imageSetterCallsRef) {
      imageSetterCallsRef.current += 1;
    }
    setSessionImageAttachmentsState(next);
  }, [imageSetterCallsRef]);
  const actions = useChatComposerSubmitActions({
    ...mutations,
    queryClient,
    lang: "zh",
    describeError: (error, fallback) => (error instanceof Error ? error.message : fallback),
    setSessionDrafts,
    sessionFollowupQueues: {},
    setSessionComposerErrors,
    setSessionImageAttachments,
    setSessionReferenceAttachments,
    setSessionImageUploadPending,
    setSessionEditTargets,
    imageUploadInFlightRef,
    activeSessionId,
    activeDraftEffective: sessionDrafts[activeSessionId] ?? "",
    activeImageAttachments: sessionImageAttachments,
    activeReferenceAttachments: sessionReferenceAttachments[activeSessionId] ?? [],
    mentalModelEnabledForNextTurn: false,
    runtimeStatusEnabledForNextTurn: false,
    turnModelSelection: null,
    resolvedEditTarget: null,
    activeEditTarget: null,
    composerDisabled: false,
    sessionBusy: false,
    sessionStopping: false,
    activePhase: "ready",
    activeAgentImageInputUnsupported: unsupportedImages,
    activeImageInputModelId: "model-1",
    latestUserMessageId: "user-1",
    activeTurnId: undefined,
    detail: undefined,
    setMentalModelEnabledForNextTurn: () => undefined,
    setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  if (actionsRef) {
    actionsRef.current = actions;
  }
  return (
    <div>
      <output data-testid="session">{activeSessionId}</output>
      <output data-testid="attachments">
        {JSON.stringify(sessionImageAttachments.map(({ id, previewUrl }) => ({ id, previewUrl })))}
      </output>
      <button type="button" data-testid="switch-session" onClick={() => setActiveSessionId("session-b")}>
        switch
      </button>
      <button type="button" data-testid="return-session" onClick={() => setActiveSessionId("session-a")}>
        return
      </button>
      <button type="button" data-testid="submit" onClick={() => actions.handleSubmitTurn()}>
        submit
      </button>
      <button type="button" data-testid="remove" onClick={() => actions.handleRemoveComposerAttachment("image-a")}>
        remove
      </button>
    </div>
  );
}

function mount(ui: React.ReactElement): { root: Root; container: HTMLDivElement } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  return { root, container };
}

async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function unmount(root: Root, container: HTMLDivElement) {
  await act(async () => {
    root.unmount();
    await Promise.resolve();
    await Promise.resolve();
  });
  container.remove();
}

const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
const objectUrlMocks = vi.hoisted(() => ({
  create: vi.fn(),
  revoke: vi.fn(),
}));

beforeEach(() => {
  let nextPreviewId = 0;
  objectUrlMocks.create.mockReset().mockImplementation(() => `blob:restored-${++nextPreviewId}`);
  objectUrlMocks.revoke.mockReset();
  apiMocks.uploadSessionImageAttachment.mockReset().mockResolvedValue({ artifactId: "artifact-uploaded" });
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: objectUrlMocks.create });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: objectUrlMocks.revoke });
});

afterEach(() => {
  if (originalCreateObjectURL) {
    Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
  } else {
    Reflect.deleteProperty(URL, "createObjectURL");
  }
  if (originalRevokeObjectURL) {
    Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
  } else {
    Reflect.deleteProperty(URL, "revokeObjectURL");
  }
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("useChatComposerSubmit object URL lifecycle", () => {
  it("releases previews on session switch, restores them from File, and survives StrictMode replay", async () => {
    const fileA = makeAttachment("image-a", "blob:session-a");
    const fileB = makeAttachment("image-b", "blob:session-b");
    const mounted = mount(
      <React.StrictMode>
        <Harness
          queryClient={new QueryClient()}
          mutations={makeMutations()}
          initialAttachments={{ "session-a": [fileA], "session-b": [fileB] }}
        />
      </React.StrictMode>,
    );
    await flushMicrotasks();
    expect(objectUrlMocks.revoke).not.toHaveBeenCalledWith("blob:session-a");

    act(() => {
      (mounted.container.querySelector('[data-testid="switch-session"]') as HTMLButtonElement).click();
    });
    await flushMicrotasks();
    expect(objectUrlMocks.revoke).toHaveBeenCalledWith("blob:session-a");

    act(() => {
      (mounted.container.querySelector('[data-testid="return-session"]') as HTMLButtonElement).click();
    });
    await flushMicrotasks();
    expect(objectUrlMocks.create).toHaveBeenCalledWith(fileA.file);
    expect(mounted.container.querySelector('[data-testid="attachments"]')?.textContent)
      .toContain("blob:restored-1");

    await unmount(mounted.root, mounted.container);
    expect(objectUrlMocks.revoke).toHaveBeenCalledWith("blob:restored-1");
  });

  it("revokes URLs for model-rejected classified attachments immediately", async () => {
    const addRef = { current: null as UseChatComposerSubmitActionsResult | null };
    const mounted = mount(
      <Harness
        queryClient={new QueryClient()}
        mutations={makeMutations()}
        initialAttachments={{ "session-a": [] }}
        unsupportedImages
        actionsRef={addRef}
      />,
    );
    const rejectedImage = new File(["image"], "rejected.png", { type: "image/png" });
    act(() => addRef.current?.handleAddComposerAttachments([rejectedImage]));

    expect(objectUrlMocks.create).toHaveBeenCalledTimes(1);
    expect(objectUrlMocks.revoke).toHaveBeenCalledWith("blob:restored-1");
    await unmount(mounted.root, mounted.container);
    expect(objectUrlMocks.revoke).toHaveBeenCalledTimes(1);
  });

  it("does not submit a deleted attachment after its upload finishes late", async () => {
    let finishUpload: ((result: { artifactId: string }) => void) | undefined;
    apiMocks.uploadSessionImageAttachment.mockImplementation(() => new Promise((resolve) => {
      finishUpload = resolve;
    }));
    const attachment = makeAttachment("image-a", "blob:image-a");
    const mutations = makeMutations();
    const actionsRef = { current: null as UseChatComposerSubmitActionsResult | null };
    const mounted = mount(
      <Harness
        queryClient={new QueryClient()}
        mutations={mutations}
        initialAttachments={{ "session-a": [attachment] }}
        actionsRef={actionsRef}
      />,
    );

    act(() => actionsRef.current?.handleSubmitTurn());
    expect(apiMocks.uploadSessionImageAttachment).toHaveBeenCalledTimes(1);
    act(() => actionsRef.current?.handleRemoveComposerAttachment("image-a"));
    await act(async () => {
      finishUpload?.({ artifactId: "artifact-uploaded" });
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mutations.submitTurnMutation.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ attachmentIds: [] }),
    );
    expect(mounted.container.querySelector('[data-testid="attachments"]')?.textContent).toBe("[]");
    expect(objectUrlMocks.revoke).toHaveBeenCalledWith("blob:image-a");
    await unmount(mounted.root, mounted.container);
  });

  it("does not update attachment state when an upload resolves after unmount", async () => {
    let finishUpload: ((result: { artifactId: string }) => void) | undefined;
    apiMocks.uploadSessionImageAttachment.mockImplementation(() => new Promise((resolve) => {
      finishUpload = resolve;
    }));
    const attachment = makeAttachment("image-a", "blob:image-a");
    const mutations = makeMutations();
    const imageSetterCallsRef = { current: 0 };
    const mounted = mount(
      <Harness
        queryClient={new QueryClient()}
        mutations={mutations}
        initialAttachments={{ "session-a": [attachment] }}
        imageSetterCallsRef={imageSetterCallsRef}
      />,
    );

    act(() => {
      (mounted.container.querySelector('[data-testid="submit"]') as HTMLButtonElement).click();
    });
    expect(apiMocks.uploadSessionImageAttachment).toHaveBeenCalledTimes(1);
    const setterCallsAtUnmount = imageSetterCallsRef.current;
    await unmount(mounted.root, mounted.container);

    await act(async () => {
      finishUpload?.({ artifactId: "artifact-uploaded" });
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(imageSetterCallsRef.current).toBe(setterCallsAtUnmount);
    expect(mutations.submitTurnMutation.mutate).not.toHaveBeenCalled();
    expect(objectUrlMocks.revoke).toHaveBeenCalledWith("blob:image-a");
  });
});
