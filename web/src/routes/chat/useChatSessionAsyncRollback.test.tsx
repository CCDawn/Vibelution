// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useChatSessionDetailMutations } from "./useChatSessionDetailMutations";
import { queryKeys } from "../../api/queryKeys";
import { resolveSessionToolApprovalDecision } from "../../api/chat";
import { deleteChatSession } from "../../api/chat";
import { useChatWorkspaceLifecycle } from "./useChatWorkspaceLifecycle";
import { bulkDeleteChatSessions } from "../../api/chat";
import {
  isSessionDeleteTombstoned,
  resetSessionDeleteTombstonesForTests,
} from "../sessionDeleteTombstone";
vi.mock("../../api/chat", async (original) => ({
  ...(await original()),
  resolveSessionToolApprovalDecision: vi.fn(),
  deleteChatSession: vi.fn(),
  bulkDeleteChatSessions: vi.fn(),
}));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({
    succeeded: vi.fn(),
    failed: vi.fn(),
    blocked: vi.fn(),
  }),
}));
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
let hooks: ReturnType<typeof useChatSessionDetailMutations>;
const sessionId = "s";
function deferred() {
  let resolve!: (value: any) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<any>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
let cleanup: () => Promise<void> = async () => {};
async function mount(client: QueryClient) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const root = createRoot(el);
  function Harness() {
    hooks = useChatSessionDetailMutations({
      queryClient: client,
      chatWorkspaceCache: {
        refreshSessionRuntime: vi.fn(),
        afterSessionChanged: vi.fn(),
      } as any,
      lang: "zh",
      describeError: () => "",
      activeSessionId: sessionId,
      setSessionComposerErrors: vi.fn(),
    });
    return null;
  }
  await act(async () =>
    root.render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    ),
  );
  cleanup = async () => {
    await act(async () => root.unmount());
    el.remove();
    client.clear();
  };
}
async function flush(action: () => void) {
  await act(async () => {
    action();
    await new Promise((r) => setTimeout(r, 0));
  });
}
afterEach(async () => {
  await cleanup();
  vi.clearAllMocks();
  resetSessionDeleteTombstonesForTests();
});
describe("cross-layer flow boundaries", () => {
  it.each([false, true])(
    "restores only an unsuperseded failed approval (same request=%s)",
    async (sameRequest) => {
      const client = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      vi.spyOn(client, "invalidateQueries").mockResolvedValue(undefined);
      const req = (id: string) => ({ requestId: id, sessionId });
      const secondId = sameRequest ? "A" : "B";
      const first = deferred();
      const second = deferred();
      vi.mocked(resolveSessionToolApprovalDecision).mockImplementation(
        (_: any, decision: any) =>
          decision === "accept" ? first.promise : second.promise,
      );
      client.setQueryData(queryKeys.sessionToolApprovals(sessionId), [
        req("A"),
        req("B"),
      ]);
      await mount(client);
      await flush(() =>
        hooks.resolveSessionToolApprovalMutation.mutate({
          request: req("A") as any,
          decision: "accept",
        }),
      );
      await flush(() =>
        hooks.resolveSessionToolApprovalMutation.mutate({
          request: req(secondId) as any,
          decision: "decline",
        }),
      );
      await flush(() => second.resolve(req(secondId)));
      // Fresh pending requests returned by the normal polling owner.
      client.setQueryData(queryKeys.sessionToolApprovals(sessionId), [
        req("C"),
      ]);
      await flush(() => first.reject(new Error("A failed")));
      const ids = (
        client.getQueryData<any[]>(queryKeys.sessionToolApprovals(sessionId)) ??
        []
      ).map((r) => r.requestId);
      expect(ids).toEqual(sameRequest ? ["C"] : ["C", "A"]);
    },
  );
  it.each([
    "single-error",
    "bulk-error",
    "bulk-skipped",
    "bulk-mixed",
    "single-success",
    "single-unconfirmed",
  ])(
    "preserves drafts until precise deletion confirmation (%s)",
    async (mode) => {
      const bulk = mode.startsWith("bulk");
      const mixed = mode === "bulk-mixed";
      const ids = mixed
        ? [sessionId, "deleted", "missing", "failed"]
        : [sessionId];
      const client = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      const pending = deferred();
      vi.mocked(deleteChatSession).mockReturnValue(pending.promise);
      vi.mocked(bulkDeleteChatSessions).mockReturnValue(pending.promise);
      const drafts: Record<string, string> = Object.fromEntries(
        ids.map((id) => [id, "unsent message"]),
      );
      const attachments: Record<string, string[]> = Object.fromEntries(
        ids.map((id) => [id, ["image-1"]]),
      );
      client.setQueryData(
        queryKeys.sessions(),
        ids.map((id) => ({ id, agentId: "agent" })),
      );
      const noop = vi.fn();
      let lifecycle: ReturnType<typeof useChatWorkspaceLifecycle>;
      function Harness() {
        lifecycle = useChatWorkspaceLifecycle({
          queryClient: client,
          chatWorkspaceCache: {
            refreshSessionRuntime: noop,
            afterSessionDeleted: noop,
          } as any,
          lang: "zh",
          t: (key: any) => key,
          describeError: () => "",
          syncSessionDetail: noop,
          syncChatRoomDetail: noop,
          clearSessionTransientUiState: (id: string) => {
            delete drafts[id];
            delete attachments[id];
            client.removeQueries({
              queryKey: queryKeys.session(id),
              exact: true,
            });
          },
          removeSessionWorkspace: noop,
          rebaseSessionComposerState: noop,
          requestSessionComposerFocus: noop,
          routeSelectionRef: { current: { kind: "bare" } },
          chatRoute: {
            openSession: noop,
            openRoom: noop,
            replaceIfStillViewing: () => false,
          },
          setRightIndexPanel: noop,
          setSelectedAgentId: noop,
          setSessionFilter: noop,
          setSessionComposerErrors: noop,
          setGroupComposerOpen: noop,
          setGroupTitleDraft: noop,
          setGroupModeDraft: noop,
          setGroupPurposeDraft: noop,
          setGroupSelectedAgentIds: noop,
          setGroupTopicDraft: noop,
          setGroupRoomActionError: noop,
          setGroupManageTitleDraft: noop,
          setGroupManageSessionIds: noop,
          setGroupManageModeDraft: noop,
          setGroupManagePurposeDraft: noop,
          setProjectBusDraft: noop,
          editingSessionIdRef: { current: null },
          editingSessionTitleRef: { current: "" },
          setEditingSessionId: noop,
          setEditingSessionTitle: noop,
          suppressRenameBlurUntilRef: { current: 0 },
        } as any);
        return null;
      }
      const el = document.createElement("div");
      document.body.appendChild(el);
      const root = createRoot(el);
      await act(async () =>
        root.render(
          <QueryClientProvider client={client}>
            <Harness />
          </QueryClientProvider>,
        ),
      );
      cleanup = async () => {
        await act(async () => root.unmount());
        el.remove();
        client.clear();
      };
      await flush(() =>
        bulk
          ? lifecycle.bulkDeleteSessionsMutation.mutate({ sessionIds: ids })
          : lifecycle.deleteSessionMutation.mutate({ sessionId }),
      );
      client.setQueryData(queryKeys.sessions(), [
        { id: "new-session", agentId: "agent" },
      ]);
      await flush(() => {
        if (mode.endsWith("error"))
          pending.reject(new Error("delete rejected"));
        else if (!bulk)
          pending.resolve({ deleted: mode === "single-success", deletedSessionId: sessionId });
        else
          pending.resolve({
            status: "completed",
            requestedSessionIds: ids,
            success: mixed ? [{ sessionId: "deleted", deleted: true }] : [],
            skipped: [
              { sessionId, reason: "busy" },
              ...(mixed ? [{ sessionId: "missing", reason: "not_found" }] : []),
            ],
            failed: mixed ? [{ sessionId: "failed", reason: "error" }] : [],
            summary: {
              requestedCount: ids.length,
              successCount: mixed ? 1 : 0,
              skippedCount: mixed ? 2 : 1,
              failedCount: mixed ? 1 : 0,
            },
          });
      });
      if (mode === "single-success") {
        expect(drafts[sessionId]).toBeUndefined();
        expect(attachments[sessionId]).toBeUndefined();
        return;
      }
      if (mixed) {
        for (const deletedId of ["deleted", "missing"]) {
          expect(drafts[deletedId]).toBeUndefined();
          expect(attachments[deletedId]).toBeUndefined();
          expect(isSessionDeleteTombstoned(deletedId)).toBe(true);
        }
        expect(drafts.failed).toBe("unsent message");
        expect(isSessionDeleteTombstoned("failed")).toBe(false);
      }
      expect(isSessionDeleteTombstoned(sessionId)).toBe(false);
      expect(
        client.getQueryData<any[]>(queryKeys.sessions())?.map((s) => s.id),
      ).toEqual(
        mixed
          ? ["new-session", sessionId, "failed"]
          : ["new-session", sessionId],
      );
      expect(drafts[sessionId]).toBe("unsent message");
      expect(attachments[sessionId]).toEqual(["image-1"]);
    },
  );
});
