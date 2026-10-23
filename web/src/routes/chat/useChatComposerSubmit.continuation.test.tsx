// @vitest-environment happy-dom
import React, { act, useMemo, useRef, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { submitSessionMessage } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionReferenceAttachment, SessionTurnAcceptedResponse } from "../../api/types";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { createActiveTurnLayersStore } from "./activeTurnLayersStore";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import { flushPendingSessionDraftWrites, readStoredSessionDrafts, resetChatDraftPersistenceForTests } from "./chatDraftPersistence";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import { useChatComposerSubmitActions } from "./useChatComposerSubmit";
import { useChatComposerTurnMutations } from "./useChatComposerTurnMutations";

vi.mock("../../api/chat", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/chat")>(), submitSessionMessage: vi.fn(),
}));
vi.mock("./chatSessionDetailHelpers", async (importOriginal) => ({
  ...await importOriginal<typeof import("./chatSessionDetailHelpers")>(), fetchSessionDetailWindow: vi.fn(),
}));
vi.mock("./chatSubmitTelemetry", () => ({ postSubmitTelemetry: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn(), blocked: vi.fn() }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const sid = "continuation-session";
const continuation = { turnId: "stopped-turn", headId: "stopped-leaf", ledgerSeq: 12, agentId: "agent-a" };
const stoppedDetail = {
  id: sid, agentId: continuation.agentId, activeLeafId: continuation.headId,
  ledgerSeq: continuation.ledgerSeq, lastTurnTerminalTurnId: continuation.turnId,
  terminalReason: "stopped_by_user", currentPhase: "ready", messages: [], queuedTurns: [],
} as unknown as SessionDetail;

type Controls = {
  continue: () => void;
  change: (draft: string) => void;
  addAttachment: (attachment: ComposerImageAttachment) => void;
  addReference: (reference: SessionReferenceAttachment) => void;
  draft: string;
  attachments: ComposerImageAttachment[];
  references: SessionReferenceAttachment[];
  error: string;
  pending: boolean;
};
let controls: Controls;
const roots: Root[] = [];
const clients: QueryClient[] = [];

function Harness({ client }: { client: QueryClient }) {
  const [drafts, setDrafts] = useState<Record<string, string>>({ [sid]: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [images, setImages] = useState<Record<string, ComposerImageAttachment[]>>({ [sid]: [] });
  const [references, setReferences] = useState<Record<string, SessionReferenceAttachment[]>>({ [sid]: [] });
  const activeTurnLayersStore = useMemo(() => createActiveTurnLayersStore(), []);
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(client), [client]);
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const mutations = useChatComposerTurnMutations({
    queryClient: client, chatWorkspaceCache, activeSessionId: sid, activeTurnLayersStore,
    t: (key) => key,
    describeError: (error, fallback) => error instanceof Error ? error.message : fallback,
    syncSessionDetail: (incoming) => client.setQueryData(queryKeys.session(incoming.id), incoming),
    setActiveTurnLayersBySession: activeTurnLayersStore.setActiveTurnLayersBySession,
    setSessionDrafts: setDrafts, setSessionComposerErrors: setErrors,
    setSessionImageAttachments: setImages, setSessionReferenceAttachments: setReferences,
    setSessionEditTargets: () => undefined,
  });
  const actions = useChatComposerSubmitActions({
    ...mutations, queryClient: client, lang: "zh",
    describeError: (error, fallback) => error instanceof Error ? error.message : fallback,
    setSessionDrafts: setDrafts, setSessionComposerErrors: setErrors,
    setSessionImageAttachments: setImages, setSessionReferenceAttachments: setReferences,
    setSessionImageUploadPending: () => undefined, setSessionEditTargets: () => undefined,
    sessionFollowupQueues: {}, imageUploadInFlightRef, activeSessionId: sid,
    activeDraftEffective: drafts[sid] ?? "", activeImageAttachments: images[sid] ?? [],
    activeReferenceAttachments: references[sid] ?? [],
    mentalModelEnabledForNextTurn: false, runtimeStatusEnabledForNextTurn: true,
    turnModelSelection: null, resolvedEditTarget: null, activeEditTarget: null,
    composerDisabled: false, sessionBusy: false, sessionStopping: false, activePhase: "ready",
    activeAgentImageInputUnsupported: false, activeImageInputModelId: "model-a",
    latestUserMessageId: "", activeTurnId: undefined, detail: stoppedDetail, continueEnabled: true,
    setMentalModelEnabledForNextTurn: () => undefined, setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  controls = {
    continue: actions.handleContinueTurn, change: actions.handleComposerChange,
    addAttachment: (attachment) => setImages((current) => ({ ...current, [sid]: [...(current[sid] ?? []), attachment] })),
    addReference: actions.handleAddComposerReference,
    draft: drafts[sid] ?? "", attachments: images[sid] ?? [], references: references[sid] ?? [],
    error: errors[sid] ?? "", pending: mutations.submitTurnMutation.isPending,
  };
  return null;
}

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  client.setQueryData(queryKeys.session(sid), stoppedDetail);
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container); roots.push(root);
  await act(async () => root.render(<QueryClientProvider client={client}><Harness client={client} /></QueryClientProvider>));
  return client;
}

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
}

beforeEach(() => {
  localStorage.clear(); resetChatDraftPersistenceForTests();
  vi.mocked(submitSessionMessage).mockReset();
  vi.mocked(fetchSessionDetailWindow).mockReset().mockRejectedValue(new Error("readback unavailable"));
});
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => root.unmount());
  for (const client of clients.splice(0)) client.clear();
  resetChatDraftPersistenceForTests(); document.body.replaceChildren();
});

describe("Play through native composer submit hooks", () => {
  it.each(["", "请求期间写入的新草稿"])("does not restore synthetic continuation after failure (draft=%j)", async (newDraft) => {
    let rejectSubmit!: (error: Error) => void;
    vi.mocked(submitSessionMessage).mockReturnValue(new Promise((_resolve, reject) => { rejectSubmit = reject; }));
    const client = await mount();
    await act(async () => controls.continue());
    await settle();
    expect(submitSessionMessage).toHaveBeenCalledOnce();
    expect(vi.mocked(submitSessionMessage).mock.calls[0]).toEqual([sid, expect.objectContaining({
      content: "继续", contentUtf8Base64: "57un57ut", queueIfBusy: false, continuation,
      attachmentIds: [], references: [],
    })]);
    expect(client.getQueryData<SessionDetail>(queryKeys.session(sid))?.messages)
      .toEqual(expect.arrayContaining([expect.objectContaining({ role: "user", content: "继续" })]));
    if (newDraft) await act(async () => controls.change(newDraft));
    await act(async () => rejectSubmit(new Error("submit disconnected")));
    await settle();

    expect(fetchSessionDetailWindow).toHaveBeenCalledOnce();
    expect(controls.error).not.toBe("");
    expect(controls.pending).toBe(false);
    expect(controls.draft).toBe(newDraft);
    flushPendingSessionDraftWrites();
    expect(readStoredSessionDrafts()[sid] ?? "").toBe(newDraft);
    expect(client.getQueryData<SessionDetail>(queryKeys.session(sid))?.messages
      .some((message) => message.role === "user" && message.content === "继续")).toBe(false);
  });

  it("preserves draft, attachment and reference added while the continuation is in flight", async () => {
    let acceptSubmit!: (receipt: SessionTurnAcceptedResponse) => void;
    vi.mocked(submitSessionMessage).mockReturnValue(new Promise((resolve) => { acceptSubmit = resolve; }));
    await mount();
    await act(async () => controls.continue());
    await settle();
    expect(submitSessionMessage).toHaveBeenCalledOnce();
    expect(controls.pending).toBe(true);
    const request = vi.mocked(submitSessionMessage).mock.calls[0][1];
    expect(request.continuation).toEqual(continuation);
    expect(request.queueIfBusy).toBe(false);
    const newAttachment: ComposerImageAttachment = {
      id: "new-image", file: new File(["next image"], "next.png", { type: "image/png" }),
      filename: "next.png", previewUrl: null, sizeBytes: 10, contentType: "image/png", kind: "image",
    };
    const newReference: SessionReferenceAttachment = {
      referenceId: "message:source-session:source-message",
      kind: "message", sourceSessionId: "source-session", sourceMessageId: "source-message", quote: "新引用",
    };
    await act(async () => {
      controls.change("下一轮的新草稿"); controls.addAttachment(newAttachment); controls.addReference(newReference);
    });
    expect(controls.draft).toBe("下一轮的新草稿");
    expect(controls.attachments).toEqual([newAttachment]);
    expect(controls.references).toEqual([newReference]);
    await act(async () => acceptSubmit({
      accepted: true, sessionId: sid, clientSubmissionId: request.clientSubmissionId,
      turnId: "continued-turn", status: "accepted", acceptedAt: "2026-10-23T00:00:00.000Z",
    }));
    await settle();

    expect(controls.pending).toBe(false);
    expect(controls.error).toBe("");
    expect(controls.draft).toBe("下一轮的新草稿");
    expect(controls.attachments).toEqual([newAttachment]);
    expect(controls.references).toEqual([newReference]);
    flushPendingSessionDraftWrites();
    expect(readStoredSessionDrafts()[sid]).toBe("下一轮的新草稿");
    expect(request.attachmentIds).toEqual([]);
    expect(request.references).toEqual([]);
  });
});
