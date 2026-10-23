// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useChatSessionMutations } from "./useChatSessionMutations";
import { useChatGroupWorkspaceMutations } from "./useChatGroupWorkspaceMutations";
import { useChatWorkspaceActions } from "./useChatWorkspaceActions";

const transport = vi.hoisted(() => ({ archive: vi.fn(), start: vi.fn(), update: vi.fn(), remove: vi.fn() }));
vi.mock("../../api/sessionArchive", () => ({ archiveChatSession: transport.archive, unarchiveChatSession: transport.archive }));
vi.mock("../../api/chat", async (original) => ({
  ...await original<typeof import("../../api/chat")>(),
  startChatRoomRound: transport.start, updateChatRoom: transport.update, deleteChatRoom: transport.remove,
}));
vi.mock("../../app/userActionTelemetry", () => ({ startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn(), blocked: vi.fn() }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function deferred<T = unknown>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
let client: QueryClient;
let root: Root;
let host: HTMLDivElement;
let sessions: ReturnType<typeof useChatSessionMutations>;
let groups: ReturnType<typeof useChatGroupWorkspaceMutations>;
let actions: ReturnType<typeof useChatWorkspaceActions>;
let roomId: string;
let route: { current: { kind: "room"; roomId: string } };
let refresh: ReturnType<typeof vi.fn>;
let topic: ReturnType<typeof vi.fn>;
let title: ReturnType<typeof vi.fn>;
let participants: ReturnType<typeof vi.fn>;
const noOp = () => undefined;
function Probe() {
  const cache = { afterSessionChanged: refresh, afterChatRoomChanged: refresh, afterGroupRoundStarted: refresh };
  sessions = useChatSessionMutations({ queryClient: client, chatWorkspaceCache: cache, lang: "zh", t: (key: string) => key,
    setSessionComposerErrors: noOp, latestDirectSessionSelectionRef: { current: null }, directSessionSelectionGenerationRef: { current: 0 },
    activeSessionId: "", syncSessionDetail: noOp, openSession: noOp,
  } as unknown as Parameters<typeof useChatSessionMutations>[0]);
  groups = useChatGroupWorkspaceMutations({ queryClient: client, chatWorkspaceCache: cache, lang: "zh", describeError: (e: Error) => e.message,
    routeSelectionRef: route, chatRoute: { replaceIfStillViewing: () => false }, syncChatRoomDetail: noOp,
    setGroupTopicDraft: topic, setGroupManageTitleDraft: title, setGroupManageSessionIds: participants,
    setGroupManageModeDraft: noOp, setGroupManagePurposeDraft: noOp, setGroupRoomActionError: noOp, setRightIndexPanel: noOp,
  } as unknown as Parameters<typeof useChatGroupWorkspaceMutations>[0]);
  actions = useChatWorkspaceActions({ lang: "zh", t: (key: string) => key, activeGroupRoom: { roomId }, standardGroupRoomActive: true,
    ...groups, groupTopicDraft: "B topic", groupRoundActive: false,
    deleteSessionMutation: { isPending: false }, clearSessionHistoryMutation: { isPending: false }, addSessionToReviewMutation: { isPending: false },
  } as unknown as Parameters<typeof useChatWorkspaceActions>[0]);
  return null;
}
async function render() { await act(async () => { root.render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>); }); }
async function flush() { await act(async () => { await new Promise(done => setTimeout(done, 0)); }); }
beforeEach(async () => {
  vi.clearAllMocks(); roomId = "A"; route = { current: { kind: "room", roomId } };
  refresh = vi.fn().mockResolvedValue(undefined); topic = vi.fn(); title = vi.fn(); participants = vi.fn();
  client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host); await render();
});
afterEach(() => { act(() => root.unmount()); host.remove(); client.clear(); });

it("settles the archive write while authoritative readback is still waiting", async () => {
  refresh.mockReturnValue(new Promise(() => undefined)); transport.archive.mockResolvedValue({ sessionId: "A", status: "archived" });
  act(() => sessions.sessionArchiveMutation.mutate({ sessionId: "A", archive: true })); await flush();
  expect(refresh).toHaveBeenCalledWith({ sessionId: "A" });
  expect(sessions.sessionArchiveMutation.isPending).toBe(false);
});

it("keeps a successful archive successful when background readback rejects", async () => {
  refresh.mockRejectedValue(new Error("readback unavailable")); transport.archive.mockResolvedValue({ sessionId: "A", status: "archived" });
  act(() => sessions.sessionArchiveMutation.mutate({ sessionId: "A", archive: true })); await flush();
  expect(sessions.sessionArchiveMutation.isSuccess).toBe(true);
  expect(transport.archive).toHaveBeenCalledTimes(1);
});

it("does not retry a timed out archive and reconciles only its target", async () => {
  transport.archive.mockRejectedValue(new DOMException("timeout", "TimeoutError"));
  act(() => sessions.sessionArchiveMutation.mutate({ sessionId: "A", archive: true })); await flush();
  expect(sessions.sessionArchiveMutation.isPending).toBe(false);
  expect(transport.archive).toHaveBeenCalledTimes(1);
  expect(refresh).toHaveBeenCalledWith({ sessionId: "A" });
});

it("keeps every archive ID pending when a later independent archive settles first", async () => {
  const a = deferred(); const b = deferred(); transport.archive.mockImplementation((id: string) => id === "A" ? a.promise : b.promise);
  act(() => sessions.sessionArchiveMutation.mutate({ sessionId: "A", archive: true })); await flush();
  act(() => sessions.sessionArchiveMutation.mutate({ sessionId: "B", archive: true })); await flush();
  await act(async () => { b.resolve({ sessionId: "B" }); }); await flush();
  const mutation = sessions.sessionArchiveMutation as typeof sessions.sessionArchiveMutation & { isPendingFor?: (id: string) => boolean };
  expect(mutation.isPendingFor?.("A")).toBe(true); expect(mutation.isPendingFor?.("B")).toBe(false);
  await act(async () => { a.resolve({ sessionId: "A" }); });
});

it("starts room B while room A admission is pending and keeps A pending after B settles", async () => {
  const a = deferred(); const b = deferred(); transport.start.mockImplementation((id: string) => id === "A" ? a.promise : b.promise);
  act(() => actions.handleStartGroupRound()); await flush();
  roomId = "B"; route.current = { kind: "room", roomId }; await render();
  act(() => actions.handleStartGroupRound()); await flush();
  expect(transport.start.mock.calls.map(call => call[0])).toEqual(["A", "B"]);
  act(() => actions.handleStartGroupRound()); await flush();
  expect(transport.start).toHaveBeenCalledTimes(2);
  await act(async () => { b.resolve({ roomId: "B", roundId: "b" }); }); await flush();
  const mutation = groups.startGroupRoundMutation as typeof groups.startGroupRoundMutation & { isPendingFor?: (id: string) => boolean };
  expect(mutation.isPendingFor?.("A")).toBe(true);
  await act(async () => { a.resolve({ roomId: "A", roundId: "a" }); }); await flush();
});

it.each(["update", "delete", "start"] as const)("keeps B drafts when A %s succeeds late", async (operation) => {
  const pending = deferred(); transport.update.mockReturnValue(pending.promise); transport.remove.mockReturnValue(pending.promise); transport.start.mockReturnValue(pending.promise);
  act(() => {
    if (operation === "update") groups.updateGroupRoomMutation.mutate({ roomId: "A", title: "A title", sessionIds: ["a1", "a2"], mode: "round_robin", purpose: "discussion" });
    else if (operation === "delete") groups.deleteGroupRoomMutation.mutate({ roomId: "A" });
    else groups.startGroupRoundMutation.mutate({ roomId: "A", topic: "A topic", mode: "round_robin", purpose: "discussion" });
  }); await flush();
  roomId = "B"; route.current = { kind: "room", roomId }; await render(); topic.mockClear(); title.mockClear(); participants.mockClear();
  await act(async () => { pending.resolve({ roomId: "A", roundId: "a", title: "A title", participants: [{ sessionId: "a1" }, { sessionId: "a2" }] }); }); await flush();
  expect(topic).not.toHaveBeenCalled(); expect(title).not.toHaveBeenCalled(); expect(participants).not.toHaveBeenCalled();
});
