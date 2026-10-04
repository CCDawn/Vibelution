// @vitest-environment happy-dom
import React, { act, useRef, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { submitSessionMessage, uploadSessionImageAttachment } from "../../api/chat";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { useChatComposerSubmitActions, useChatComposerTurnMutations } from "./useChatComposerSubmit";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import { flushPendingSessionDraftWrites, readStoredSessionDrafts, resetChatDraftPersistenceForTests } from "./chatDraftPersistence";

vi.mock("../../api/chat", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/chat")>(),
  submitSessionMessage: vi.fn(),
  uploadSessionImageAttachment: vi.fn(),
}));
vi.mock("./chatSubmitTelemetry", () => ({ postSubmitTelemetry: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn(), blocked: vi.fn() }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const sid = "draft-recovery-session";
const originalDraft = "发送失败后仍需要保留的文字";
let controls: { change: (value: string) => void; submit: () => void; draft: string; error: string };
const roots: Root[] = [];
const clients: QueryClient[] = [];

function Harness({ client, attachments }: { client: QueryClient; attachments: ComposerImageAttachment[] }) {
  const [drafts, setDrafts] = useState<Record<string, string>>({ [sid]: originalDraft });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [images, setImages] = useState<Record<string, ComposerImageAttachment[]>>({ [sid]: attachments });
  const uploadInFlight = useRef<Record<string, boolean>>({});
  const mutations = useChatComposerTurnMutations({
    queryClient: client,
    chatWorkspaceCache: createChatWorkspaceCache(client),
    t: ((key: string) => key) as never,
    describeError: (error, fallback) => error instanceof Error ? error.message : fallback,
    syncSessionDetail: () => undefined,
    setActiveTurnLayersBySession: () => undefined,
    setSessionDrafts: setDrafts,
    setSessionComposerErrors: setErrors,
    setSessionImageAttachments: setImages,
    setSessionReferenceAttachments: () => undefined,
    setSessionEditTargets: () => undefined,
  });
  const actions = useChatComposerSubmitActions({
    ...mutations, queryClient: client, lang: "zh",
    describeError: (error, fallback) => error instanceof Error ? error.message : fallback,
    setSessionDrafts: setDrafts, setSessionComposerErrors: setErrors,
    setSessionImageAttachments: setImages, setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined, setSessionEditTargets: () => undefined,
    sessionFollowupQueues: {}, imageUploadInFlightRef: uploadInFlight,
    activeSessionId: sid, activeDraftEffective: drafts[sid] ?? "",
    activeImageAttachments: images[sid] ?? [], activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false, runtimeStatusEnabledForNextTurn: false,
    turnModelSelection: null, resolvedEditTarget: null, activeEditTarget: null,
    composerDisabled: false, sessionBusy: false, sessionStopping: false, activePhase: "ready",
    activeAgentImageInputUnsupported: false, activeImageInputModelId: "model-1",
    latestUserMessageId: "", activeTurnId: undefined, detail: undefined,
    setMentalModelEnabledForNextTurn: () => undefined, setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  controls = { change: actions.handleComposerChange, submit: actions.handleSubmitTurn, draft: drafts[sid] ?? "", error: errors[sid] ?? "" };
  return null;
}

function mount(attachments: ComposerImageAttachment[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  act(() => root.render(<QueryClientProvider client={client}><Harness client={client} attachments={attachments} /></QueryClientProvider>));
  act(() => controls.change(originalDraft));
  flushPendingSessionDraftWrites();
  expect(readStoredSessionDrafts()[sid]).toBe(originalDraft);
}

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
}

beforeEach(() => {
  localStorage.clear();
  resetChatDraftPersistenceForTests();
  vi.mocked(submitSessionMessage).mockReset().mockRejectedValue(new Error("network disconnected"));
  vi.mocked(uploadSessionImageAttachment).mockReset().mockRejectedValue(new Error("upload rejected"));
});
afterEach(() => {
  roots.splice(0).forEach((root) => act(() => root.unmount()));
  clients.splice(0).forEach((client) => client.clear());
  resetChatDraftPersistenceForTests();
  document.body.replaceChildren();
});

describe("failed composer draft recovery", () => {
  it.each(["message", "attachment"])("persists the recovered text after %s failure", async (kind) => {
    const attachments: ComposerImageAttachment[] = kind === "attachment" ? [{
      id: "image-1", file: new File(["bytes"], "test.png", { type: "image/png" }),
      filename: "test.png", previewUrl: "blob:test", sizeBytes: 5, contentType: "image/png", kind: "image",
    }] : [];
    mount(attachments);
    await act(async () => controls.submit());
    await settle();
    expect(controls.error).not.toBe("");
    expect(controls.draft).toBe(originalDraft);
    flushPendingSessionDraftWrites();
    expect(readStoredSessionDrafts()[sid]).toBe(originalDraft);
    if (kind === "attachment") expect(submitSessionMessage).not.toHaveBeenCalled();
  });

  it("keeps newer input when an older message request fails", async () => {
    let rejectRequest!: (error: Error) => void;
    vi.mocked(submitSessionMessage).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject; }));
    mount();
    await act(async () => controls.submit());
    await settle();
    act(() => controls.change("用户在等待时输入的新草稿"));
    await act(async () => rejectRequest(new Error("late failure")));
    await settle();
    flushPendingSessionDraftWrites();
    expect(controls.draft).toBe("用户在等待时输入的新草稿");
    expect(readStoredSessionDrafts()[sid]).toBe("用户在等待时输入的新草稿");
  });
});
