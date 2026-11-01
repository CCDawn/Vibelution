/** @vitest-environment happy-dom */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider, useLocation, type Router } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { KernelTaskTimelinePayload, SessionDetail, SessionMessageWindow } from "../../api/types";
import { CHAT_DRAFTS_STORAGE_KEY, readStoredSessionDrafts } from "./chatDraftPersistence";
import { selectAgentMessage, useAgentMessageSelection } from "./agentMessageSelectionStore";
import { useAgentMessageRecords } from "./useAgentMessageRecords";

const api = vi.hoisted(() => ({
  fetchSessionDetail: vi.fn(), listKernelTasks: vi.fn(), getKernelTaskTimeline: vi.fn(),
  listProjectAgentBusTimeline: vi.fn(), selectChatSession: vi.fn(), submitSessionMessage: vi.fn(),
}));
vi.mock("../../api/chat", () => ({
  fetchSessionDetail: api.fetchSessionDetail,
  selectChatSession: api.selectChatSession,
  submitSessionMessage: api.submitSessionMessage,
}));
vi.mock("../../api/kernel", () => ({ listKernelTasks: api.listKernelTasks, getKernelTaskTimeline: api.getKernelTaskTimeline }));
vi.mock("../../api/projectAgentBus", () => ({ listProjectAgentBusTimeline: api.listProjectAgentBusTimeline }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const sourceA = "source-a", sourceB = "source-b", eventId = "kernel-message-a";
const failedId = `send:${sourceA}:failed-turn:failed-call`;
const at = "2026-11-01T12:00:00Z";

function timeline(): KernelTaskTimelinePayload {
  return {
    taskId: "message-task-a",
    event: {
      eventId, senderAgentId: "sender", sender: { id: "sender", displayName: "发送助手" },
      recipients: ["reviewer"], createdAt: at,
      semanticPayload: { semanticType: "agent.message", payload: { content: "目录中的发送", summary: "目录消息" } },
      metadata: { sourceSessionId: sourceA },
    },
    deliveries: [{ targetAgentId: "reviewer", targetSessionId: "review-session", inboxMessageId: "inbox-a", status: "delivered", wake: { wakeStatus: "started" } }],
  } as KernelTaskTimelinePayload;
}

function session(id: string, messages: unknown[] = []): SessionDetail {
  return { id, agentId: "sender", title: id, status: "completed", messages,
    defaultFileContext: "", previewTabs: [], activePreviewPath: "", changedFiles: [], readFiles: [],
  } as SessionDetail;
}

function failedSendHistory(): SessionDetail {
  return session(sourceA, [{
    id: "failed-assistant", role: "assistant", turnId: "failed-turn", timestamp: at, content: "", metadata: {},
    turnItems: [{
      id: "failed-call", itemId: "failed-call", sessionId: sourceA, turnId: "failed-turn",
      type: "tool_call", toolName: "agent_message_tool", status: "completed", createdAt: at,
      input: JSON.stringify({ content: "仅来源历史可见的失败发送", summary: "失败发送 X", target_agent: "reviewer", target_session: "missing-session" }),
      output: JSON.stringify({ ok: false, targetAgentId: "reviewer", targetSessionId: "missing-session", error: "SessionUnavailable", message: "Target session does not exist" }),
    }],
  }]);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function messageWindow(total: number, oldest: number, count: number): SessionMessageWindow {
  const newest = oldest + count - 1;
  return { mode: "window", totalMessages: total, returnedMessages: count, oldestMessageIndex: oldest,
    newestMessageIndex: newest, hasEarlier: oldest > 1, hasLater: newest < total,
    nextBeforeMessageIndex: oldest > 1 ? oldest : null, transcriptScope: "window" };
}

describe("useAgentMessageRecords source-history selection", () => {
  let client: QueryClient;
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;
  let router: Router | undefined;
  let latest: ReturnType<typeof useAgentMessageRecords>;
  let selected: string | null;
  let consoleError: { mock: { calls: unknown[][] } };

  function Harness({ sessionId }: { sessionId?: string }) {
    latest = useAgentMessageRecords({ sessionId });
    selected = useAgentMessageSelection();
    return <section>
      <output data-testid="selection">{selected}</output>
      <output data-testid="error">{latest.error}</output>
      <ul>{latest.records.map((record) => <li key={record.id} data-record-id={record.id}>{record.title}</li>)}</ul>
    </section>;
  }

  function RouteHarness() {
    const location = useLocation();
    return <Harness sessionId={new URLSearchParams(location.search).get("session") || undefined} />;
  }

  async function mount(element: React.ReactNode = <Harness />) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => { root!.render(<QueryClientProvider client={client}>{element}</QueryClientProvider>); });
  }

  async function until(assertion: () => void) {
    await vi.waitFor(async () => {
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
      assertion();
    }, { timeout: 2_000, interval: 10 });
  }

  function sourceObservers(id: string) {
    return client.getQueryCache().find({ queryKey: queryKeys.agentMessageSourceHistory(id), exact: true })?.getObserversCount() ?? 0;
  }

  beforeEach(() => {
    vi.clearAllMocks();
    consoleError = vi.spyOn(console, "error");
    selectAgentMessage(null);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    api.listKernelTasks.mockResolvedValue({ tasks: [{ taskId: "message-task-a", status: "completed" }], limit: 30, status: "", updatedAt: at });
    api.getKernelTaskTimeline.mockResolvedValue(timeline());
    api.listProjectAgentBusTimeline.mockResolvedValue({ events: [], activeAgentCount: 2, updatedAt: at });
    api.fetchSessionDetail.mockImplementation(async (id: string) => session(id));
    // Even an unexpected transport path must never leave this test process.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Unexpected real request")));
  });

  afterEach(async () => {
    await act(async () => { root?.unmount(); });
    root = null;
    router?.dispose();
    router = undefined;
    client.clear();
    container?.remove();
    container = null;
    selectAgentMessage(null);
    localStorage.removeItem(CHAT_DRAFTS_STORAGE_KEY);
    try {
      expect(consoleError.mock.calls.flatMap((args) => args.map(String)).join("\n"))
        .not.toMatch(/Cannot update a component|Maximum update depth/i);
    } finally {
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
    }
  });

  it("retains a history-only failed send and its active source query after selecting it in the message center", async () => {
    const history = deferred<SessionDetail>();
    api.fetchSessionDetail.mockImplementation((id: string) => {
      expect(id).toBe(sourceA);
      return history.promise;
    });
    await mount();
    await until(() => expect(latest.records.map((record) => record.id)).toEqual([eventId]));
    expect(api.fetchSessionDetail).not.toHaveBeenCalled();

    await act(async () => { selectAgentMessage(eventId); });
    await until(() => expect(api.fetchSessionDetail).toHaveBeenCalledWith(sourceA, expect.objectContaining({ messageLimit: 200, includeSecondary: false, signal: expect.any(AbortSignal) })));
    expect(latest.records.some((record) => record.id === failedId)).toBe(false);
    expect(sourceObservers(sourceA)).toBe(1);
    await act(async () => { history.resolve(failedSendHistory()); });
    await until(() => expect(latest.records.find((record) => record.id === failedId)?.recipients[0]).toMatchObject({ delivery: "failed", error: "SessionUnavailable: Target session does not exist" }));
    expect(client.getQueryData(queryKeys.session(sourceA))).toBeUndefined();

    await act(async () => { selectAgentMessage(failedId); });
    await until(() => {
      expect(selected).toBe(failedId);
      expect(latest.records.some((record) => record.id === failedId)).toBe(true);
      expect(sourceObservers(sourceA)).toBe(1);
      expect(sourceObservers("")).toBe(0);
    });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(container?.querySelector(`[data-record-id="${failedId}"]`)).not.toBeNull();
    expect(api.fetchSessionDetail).toHaveBeenCalledTimes(1);
    expect(api.fetchSessionDetail.mock.calls.map(([id]) => id)).toEqual([sourceA]);
    expect(client.getQueryData(queryKeys.agentMessageSourceHistory(sourceA))).toMatchObject({ id: sourceA });
  });

  it("follows the committed native session A to B despite an older global message selection, without route or draft writes", async () => {
    const nativeA = session(sourceA), nativeB = session(sourceB);
    client.setQueryData(queryKeys.session(sourceA), nativeA);
    client.setQueryData(queryKeys.session(sourceB), nativeB);
    const draftBytes = JSON.stringify([{ sessionId: sourceA, draft: "A 尚未发送的草稿" }, { sessionId: sourceB, draft: "B 尚未发送的草稿" }]);
    localStorage.setItem(CHAT_DRAFTS_STORAGE_KEY, draftBytes);
    const writeDraft = vi.spyOn(Storage.prototype, "setItem");
    const nativeUpdates = vi.fn();
    const unsubscribe = client.getQueryCache().subscribe((event) => {
      if (event.type === "updated" && event.query.queryKey[0] === "sessions") nativeUpdates(event);
    });
    selectAgentMessage(eventId);
    router = createMemoryRouter([{ path: "/chat", element: <RouteHarness /> }], { initialEntries: [`/chat?session=${sourceA}`] });
    const navigate = vi.spyOn(router, "navigate");
    try {
      await mount(<RouterProvider router={router} />);
      await until(() => expect(api.fetchSessionDetail.mock.calls.map(([id]) => id)).toEqual([sourceA]));
      await act(async () => { await router!.navigate(`/chat?session=${sourceB}`); });
      await until(() => {
        expect(api.fetchSessionDetail.mock.calls.map(([id]) => id)).toEqual([sourceA, sourceB]);
        expect(sourceObservers(sourceB)).toBe(1);
        expect(sourceObservers(sourceA)).toBe(0);
      });
      expect(selected).toBe(eventId);
      expect(latest.records.find((record) => record.id === eventId)?.sourceSessionId).toBe(sourceA);
      expect(router.state.location.search).toBe(`?session=${sourceB}`);
      expect(navigate).toHaveBeenCalledTimes(1); // Only the explicit native navigation above.
      expect(readStoredSessionDrafts()).toEqual({ [sourceA]: "A 尚未发送的草稿", [sourceB]: "B 尚未发送的草稿" });
      expect(localStorage.getItem(CHAT_DRAFTS_STORAGE_KEY)).toBe(draftBytes);
      expect(writeDraft).not.toHaveBeenCalled();
      expect(nativeUpdates).not.toHaveBeenCalled();
      expect(client.getQueryData(queryKeys.session(sourceA))).toBe(nativeA);
      expect(client.getQueryData(queryKeys.session(sourceB))).toBe(nativeB);
      expect(api.selectChatSession).not.toHaveBeenCalled();
      expect(api.submitSessionMessage).not.toHaveBeenCalled();
      expect(fetch).not.toHaveBeenCalled();
    } finally { unsubscribe(); }
  });

  it("keeps the existing directory visible and exposes a failed source-history read", async () => {
    api.fetchSessionDetail.mockRejectedValue(new Error("source A history unavailable"));
    await mount();
    await until(() => expect(latest.records.some((record) => record.id === eventId)).toBe(true));
    await act(async () => { selectAgentMessage(eventId); });
    await until(() => expect(latest.error).toContain("source A history unavailable"));
    expect(container?.querySelector(`[data-record-id="${eventId}"]`)).not.toBeNull();
    expect(container?.querySelector('[data-testid="error"]')?.textContent).toContain("source A history unavailable");
    expect(selected).toBe(eventId);
    expect(latest.records).toHaveLength(1);
    expect(sourceObservers(sourceA)).toBe(1);
    expect(client.getQueryState(queryKeys.agentMessageSourceHistory(sourceA))?.status).toBe("error");
    expect(api.getKernelTaskTimeline).toHaveBeenCalledTimes(1);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("retains a selected failed send from the 200-message source window when a newer native 20-message cache has the same ledger", async () => {
    const failed = { ...failedSendHistory().messages[0], id: `${sourceA}-message-40` };
    const wide: SessionDetail = {
      ...session(sourceA, Array.from({ length: 200 }, (_, offset) => {
        const index = offset + 1;
        return index === 40 ? failed : { id: `${sourceA}-message-${index}`, role: "user", content: `普通消息 ${index}`, timestamp: at };
      })),
      ledgerSeq: 500, activeBranchId: "branch-main", messageWindow: messageWindow(200, 1, 200),
    };
    api.fetchSessionDetail.mockResolvedValue(wide);
    await mount();
    await until(() => expect(latest.records.some((record) => record.id === eventId)).toBe(true));
    await act(async () => { selectAgentMessage(eventId); });
    await until(() => expect(latest.records.some((record) => record.id === failedId)).toBe(true));
    await act(async () => { selectAgentMessage(failedId); });

    const narrow: SessionDetail = { ...wide, title: "较新到达的原生窄窗口", messages: wide.messages.slice(-20), messageWindow: messageWindow(200, 181, 20) };
    expect(narrow.messages.some((message) => message.id === failed.id)).toBe(false);
    await act(async () => { client.setQueryData(queryKeys.session(sourceA), narrow, { updatedAt: Date.now() + 1_000 }); });
    await until(() => {
      expect(latest.records.find((record) => record.id === failedId)?.recipients[0].delivery).toBe("failed");
      expect(selected).toBe(failedId);
      expect(sourceObservers(sourceA)).toBe(1);
      expect(sourceObservers("")).toBe(0);
    });
    expect(client.getQueryData(queryKeys.session(sourceA))).toBe(narrow);
    expect(client.getQueryData(queryKeys.agentMessageSourceHistory(sourceA))).toBe(wide);
    expect(api.fetchSessionDetail.mock.calls.map(([id]) => id)).toEqual([sourceA]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects a lower-ledger source response arriving after the native edited branch without restoring its superseded failed send", async () => {
    const oldSource = deferred<SessionDetail>();
    api.fetchSessionDetail.mockReturnValue(oldSource.promise);
    const editedUser = { id: `${sourceA}-message-1`, role: "user", content: "编辑后的新请求", timestamp: at, metadata: { clientSubmissionId: "edited-submission" } };
    const failed = failedSendHistory().messages[0];
    if (failed.role !== "assistant") throw new Error("Expected assistant send fixture");
    const current = {
      ...failed, id: `${sourceA}-message-2`, turnId: "current-turn", branch: { branchId: "branch-current", active: true },
      turnItems: failed.turnItems!.map((item) => ({ ...item, itemId: "current-call", turnId: "current-turn", input: JSON.stringify({ content: "当前编辑分支的权威发送", summary: "当前发送", target_agent: "reviewer", target_session: "missing-session" }) })),
    };
    const currentId = `send:${sourceA}:current-turn:current-call`;
    const native: SessionDetail = {
      ...session(sourceA, [editedUser, current]), ledgerSeq: 60, activeBranchId: "branch-current", messageWindow: messageWindow(2, 1, 2),
      editResubmitProtection: { targetMessageId: editedUser.id, targetMessageIndex: 1, clientSubmissionId: "edited-submission", baseLedgerSeq: 40,
        supersededTurnId: "failed-turn", supersededTurnIds: ["failed-turn"], phase: "accepted", acceptedLedgerSeq: 60 },
    };
    client.setQueryData(queryKeys.session(sourceA), native, { updatedAt: Date.now() - 1_000 });
    selectAgentMessage(currentId);
    await mount(<Harness sessionId={sourceA} />);
    await until(() => expect(latest.records.find((record) => record.id === currentId)?.body).toBe("当前编辑分支的权威发送"));
    expect(api.fetchSessionDetail).toHaveBeenCalledTimes(1);

    const stale: SessionDetail = {
      ...session(sourceA, [
        { ...editedUser, content: "旧分支原请求", metadata: {} },
        { ...failed, id: `${sourceA}-message-2`, branch: { branchId: "branch-old", active: true } },
      ]), ledgerSeq: 40, activeBranchId: "branch-old", messageWindow: messageWindow(2, 1, 2),
    };
    await act(async () => { oldSource.resolve(stale); });
    await until(() => expect(client.getQueryData(queryKeys.agentMessageSourceHistory(sourceA))).toBe(stale));
    expect(client.getQueryState(queryKeys.agentMessageSourceHistory(sourceA))!.dataUpdatedAt)
      .toBeGreaterThan(client.getQueryState(queryKeys.session(sourceA))!.dataUpdatedAt);
    expect(latest.records.find((record) => record.id === currentId)?.body).toBe("当前编辑分支的权威发送");
    expect(latest.records.some((record) => record.id === failedId)).toBe(false);
    expect(selected).toBe(currentId);
    expect(sourceObservers(sourceA)).toBe(1);
    expect(client.getQueryData(queryKeys.session(sourceA))).toBe(native);
    expect(client.getQueryData<SessionDetail>(queryKeys.session(sourceA))?.editResubmitProtection?.phase).toBe("accepted");
    expect(fetch).not.toHaveBeenCalled();
  });
});
