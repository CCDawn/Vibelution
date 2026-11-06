// @vitest-environment happy-dom
import React, { act, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import type { LauncherAssistantDispatch } from "../../api/launcherAssistant";
import type { SessionDetail } from "../../api/types";
import { LauncherShell } from "../../app/LauncherShell";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";
import { loadLauncherComposer } from "./launcherAssistantComposerStorage";

let surface: ConversationViewProps;
vi.mock("../../components/conversation/LazyConversationView", () => ({ LazyConversationView: (props: ConversationViewProps) => {
  surface = props;
  return <div data-testid="conversation">{props.composerPrecedingContent}</div>;
} }));
vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
vi.mock("../../app/LauncherTitlebar", () => ({ LauncherTitlebar: () => null }));
vi.mock("../../app/LauncherNavigation", () => ({ LauncherNavigation: ({ taskContent }: { taskContent: ReactNode }) => taskContent }));
vi.mock("../../app/browserTelemetry", () => ({ collectBrowserPageSnapshot: () => ({}), postBrowserTelemetry: vi.fn() }));
vi.mock("../../api/launcher", () => ({
  getLauncherBranchInstances: async () => ({ currentId: "main", items: [] }),
  getLauncherFreshness: async () => ({}), hasLauncherStateBridge: () => false,
  getLauncherStatus: async () => ({ language: "zh" }),
  getLauncherState: vi.fn(), onLauncherStateChanged: vi.fn(), openLauncherModelConnection: vi.fn(),
}));

const hash = "a".repeat(64);
let root: Root | undefined;
let client: QueryClient;
let container: HTMLDivElement;
let invoke: ReturnType<typeof vi.fn>;
let detail: SessionDetail;
let rows: LauncherAssistantDispatch[];
let routeRows: LauncherAssistantDispatch[] | undefined;
let nativeApprovals: Record<string, unknown>[];
let assistant = { agentId: "assistant", directSessionId: "session", displayName: "助理" };

function dispatch(letter: string): LauncherAssistantDispatch {
  return { dispatchId: `dispatch-${letter}`, projectId: "project", agentId: `worker-${letter}`, nativeTaskId: `task-${letter}`, title: `任务 ${letter}`,
    receipt: { taskId: `task-${letter}`, status: "awaiting_approval", pendingApprovals: [{ approvalId: `approval-${letter}`, toolName: `tool-${letter}`, risk: "high",
      targetSummary: {}, revision: hash, availableDecisions: ["accept", "decline"] }] } };
}
function calls(operation: string) { return invoke.mock.calls.filter(([request]) => request.operation === operation).map(([request]) => request); }
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); }); }
async function destroy() {
  await act(async () => root?.unmount()); root = undefined; client?.clear(); container?.remove();
}
async function mount(shell = false, strict = false) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  const content = <QueryClientProvider client={client}>{shell
    ? <MemoryRouter initialEntries={["/launcher/tools"]}><Routes><Route path="/launcher" element={<LauncherShell />}>
      <Route path="tools" element={<div>Tools</div>} /><Route path="assistant" element={<LauncherAssistantRoute embedded navigationOwned />} />
    </Route></Routes></MemoryRouter>
    : <LauncherAssistantRoute embedded />}</QueryClientProvider>;
  await act(async () => root!.render(strict ? <React.StrictMode>{content}</React.StrictMode> : content));
  await settle(); await settle();
}
async function selectB() {
  const row = [...container.querySelectorAll<HTMLElement>("[data-assistant-task-id]")].find(node => node.textContent?.includes("任务 B"))!;
  expect(row).toBeDefined();
  await act(async () => row.querySelector<HTMLButtonElement>("[data-assistant-task-open]")!.click());
  await settle();
  const approve = [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(button => button.textContent === "处理授权")!;
  expect(approve).toBeDefined();
  await act(async () => approve.click()); await settle(); await settle();
}
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true); localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP forbidden"); }));
  assistant = { agentId: "assistant", directSessionId: "session", displayName: "助理" };
  rows = []; routeRows = undefined; nativeApprovals = [];
  detail = { id: "session", agentId: "assistant", status: "ready", messages: [] } as unknown as SessionDetail;
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return { assistant, settings: { ok: true, displayName: "助理", modelId: "model", preferences: {
        characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的。",
      } } };
      case "config": return { language: "zh" };
      case "detail": return detail;
      case "approvals": return nativeApprovals;
      case "resolveApproval": {
        const resolved = { ...nativeApprovals.find(row => row.requestId === request.requestId)!, status: "declined", decision: request.decision };
        nativeApprovals = nativeApprovals.map(row => row.requestId === request.requestId ? resolved : row);
        return resolved;
      }
      case "dispatches": return { dispatches: routeRows ?? rows };
      case "previewDispatchApproval": return { taskId: request.taskId, sessionId: "target-session", agentId: `worker-${String(request.dispatchId).slice(-1)}`,
        requestId: request.approvalId, turnId: "target-turn", callId: "call", toolName: `tool-${String(request.dispatchId).slice(-1)}`,
        revision: hash, approval: "on_request", risk: "high", permissionPreset: "standard", decisionFingerprint: hash, configRevision: 1,
        configHash: hash, argumentsJson: "{}", executionArgumentsJson: "{}" };
      case "send": case "continue": throw new Error("lost acknowledgement");
      default: throw new Error(`unexpected operation ${request.operation}`);
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
});
afterEach(async () => { await destroy(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

describe("Launcher task approval handoff through the real Shell and Route", () => {
  it.each([false, true])("opens B without a refresh after StrictMode replay with stale dispatch cache=%s", async cached => {
    rows = [dispatch("A"), dispatch("B")]; await mount(true, true);
    if (cached) client.setQueryData(["launcher-assistant", "dispatches", "assistant", "session", 0], [dispatch("A")], { updatedAt: 1 });
    await selectB();
    expect(client.getQueryState(["launcher-assistant", "dispatches", "assistant", "session", 0])?.error).toBeNull();
    expect(calls("previewDispatchApproval")).toEqual([{ operation: "previewDispatchApproval", dispatchId: "dispatch-B", taskId: "task-B", approvalId: "approval-B" }]);
    const dialog = document.querySelector('[data-chat-tool-approval-variant="composer"]');
    expect(dialog?.textContent).toContain("approval-B");
    expect(dialog?.textContent).not.toContain("approval-A");
  });

  it("opens the selected B approval after navigation instead of the first A approval", async () => {
    rows = [dispatch("A"), dispatch("B")]; await mount(true); await selectB();
    expect(calls("previewDispatchApproval")).toEqual([{ operation: "previewDispatchApproval", dispatchId: "dispatch-B", taskId: "task-B", approvalId: "approval-B" }]);
    const dialog = document.querySelector('[data-chat-tool-approval-variant="composer"]');
    expect(dialog?.textContent).toContain("approval-B");
    expect(dialog?.textContent).not.toContain("approval-A");
  });

  it("keeps a vanished B target unavailable without silently switching to A", async () => {
    rows = [dispatch("A"), dispatch("B")]; await mount(true);
    routeRows = [dispatch("A")]; await selectB();
    expect(calls("previewDispatchApproval")).toEqual([]);
    expect(document.querySelector('[data-chat-tool-approval-variant="composer"]')).toBeNull();
    expect(document.body.textContent).toContain("所选任务审批");
  });

  it.each(["nativeTaskId", "agentId", "approvalId"])("does not substitute a changed %s in B's receipt", async field => {
    rows = [dispatch("A"), dispatch("B")]; await mount(true);
    const changed = dispatch("B");
    if (field === "approvalId") changed.receipt!.pendingApprovals![0].approvalId = "replacement";
    else if (field === "nativeTaskId") { changed.nativeTaskId = "replacement"; changed.receipt!.taskId = "replacement"; }
    else changed.agentId = "replacement";
    routeRows = [dispatch("A"), changed]; await selectB();
    expect(calls("previewDispatchApproval")).toEqual([]);
    expect(document.body.textContent).toContain("所选任务审批");
  });

  it("keeps repeated same-page B clicks scoped and lets the user explicitly close a stale target", async () => {
    rows = [dispatch("A"), dispatch("B")]; await mount(true); await selectB();
    await selectB();
    expect(calls("previewDispatchApproval").every(request => request.approvalId === "approval-B")).toBe(true);
    rows = [dispatch("A")];
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "dispatches"] }); }); await settle();
    expect(document.querySelector('[data-chat-tool-approval-variant="composer"]')).toBeNull();
    const close = [...container.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "关闭定位")!;
    await act(async () => close.click()); await settle();
    expect(calls("previewDispatchApproval").at(-1)?.approvalId).toBe("approval-A");
  });

  it("never carries a selected target into a different assistant identity", async () => {
    rows = [dispatch("A"), dispatch("B")]; await mount(true); await selectB();
    const before = calls("previewDispatchApproval").length;
    assistant = { agentId: "other-assistant", directSessionId: "other-session", displayName: "另一助理" };
    detail = { ...detail, id: "other-session", agentId: "other-assistant" };
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "status"] }); }); await settle();
    expect(calls("previewDispatchApproval")).toHaveLength(before);
    expect(document.querySelector('[data-chat-tool-approval-variant="composer"]')).toBeNull();
    expect(document.body.textContent).toContain("所选任务审批");
  });

  it("keeps own-session approvals first and enables only that single card's shortcuts", async () => {
    rows = [dispatch("A"), dispatch("B")];
    nativeApprovals = [{ requestId: "own-approval", sessionId: "session", agentId: "assistant", turnId: "own-turn", callId: "own-call",
      toolName: "own-tool", status: "pending", risk: "high", argumentSummary: {}, availableDecisions: ["accept", "decline"] }];
    await mount(true); await selectB();
    let cards = document.querySelectorAll('[data-chat-tool-approval-variant="composer"]');
    expect(cards).toHaveLength(1); expect(cards[0].textContent).toContain("own-tool");
    expect(calls("previewDispatchApproval")).toEqual([]);
    await act(async () => cards[0].dispatchEvent(new KeyboardEvent("keydown", { key: "2", bubbles: true, cancelable: true })));
    await settle(); await settle();
    expect(calls("resolveApproval")).toEqual([{ operation: "resolveApproval", requestId: "own-approval", decision: "decline" }]);
    cards = document.querySelectorAll('[data-chat-tool-approval-variant="composer"]');
    expect(cards).toHaveLength(1); expect(cards[0].textContent).toContain("approval-B");
    expect(calls("previewDispatchApproval").every(request => request.approvalId === "approval-B")).toBe(true);
    expect(calls("decideDispatchApproval")).toEqual([]);
  });
});

describe("Launcher original request recovery with a fresh QueryClient", () => {
  it("keeps a submitted message visible before ACK and through a delayed or stale detail read", async () => {
    const fallback = invoke.getMockImplementation()!;
    let accept!: (value: unknown) => void;
    let read!: (value: SessionDetail) => void;
    let submitted = false;
    invoke.mockImplementation(async request => {
      if (request.operation === "send") {
        submitted = true;
        return new Promise(resolve => { accept = resolve; });
      }
      if (request.operation === "detail" && submitted) return new Promise(resolve => { read = resolve; });
      return fallback(request);
    });
    await mount();
    await act(async () => surface.onComposerChange!("始终可见的消息"));
    await act(async () => surface.onSubmit()); await settle();
    expect(surface.messages.filter(row => row.role === "user" && row.content === "始终可见的消息")).toHaveLength(1);
    await act(async () => accept({ accepted: true, turnId: "accepted-turn" })); await settle();
    expect(surface.composerValue).toBe("");
    expect(surface.messages.filter(row => row.role === "user" && row.content === "始终可见的消息")).toHaveLength(1);
    await act(async () => read(detail)); await settle();
    expect(surface.messages.filter(row => row.role === "user" && row.content === "始终可见的消息")).toHaveLength(1);
    const requestId = calls("send")[0].requestId;
    detail = { ...detail, messages: [{ id: "native-user", role: "user", content: "始终可见的消息", timestamp: "2026-11-06T02:00:00Z",
      metadata: { clientSubmissionId: requestId, turnId: "accepted-turn" } }] } as SessionDetail;
    const refresh = client.invalidateQueries({ queryKey: ["launcher-assistant", "detail", "session"] });
    await settle(); await act(async () => { read(detail); await refresh; }); await settle();
    expect(surface.messages.filter(row => row.role === "user")).toHaveLength(1);
    expect(surface.messages[0].id).toBe("native-user");
  });

  it("withdraws only a definitely rejected local echo and retains the draft", async () => {
    const fallback = invoke.getMockImplementation()!;
    invoke.mockImplementation(async request => {
      if (request.operation === "send") throw new Error("ASSISTANT_REQUEST_INVALID");
      return fallback(request);
    });
    detail = { ...detail, messages: [{ id: "old-user", role: "user", content: "保留的历史", timestamp: "" }] } as SessionDetail;
    await mount(); await act(async () => surface.onComposerChange!("被拒绝的消息"));
    await act(async () => surface.onSubmit()); await settle();
    expect(surface.composerValue).toBe("被拒绝的消息");
    expect(surface.messages.map(row => row.id)).toEqual(["old-user"]);
    expect(client.getQueryData<SessionDetail>(["launcher-assistant", "detail", "session"])?.status).toBe("ready");
  });

  it("shows the accepted queued message before the queue detail read completes", async () => {
    const fallback = invoke.getMockImplementation()!;
    let sent = false;
    invoke.mockImplementation(async request => {
      if (request.operation === "status") return { ...await fallback(request), followupQueueVersion: 1 };
      if (request.operation === "send") { sent = true; return { accepted: true, status: "queued", turnId: "", queuedTurnId: "q-new", clientSubmissionId: request.requestId }; }
      if (request.operation === "detail" && sent) return new Promise(() => {});
      return fallback(request);
    });
    detail = { ...detail, status: "running", currentPhase: "thinking", activeTurnId: "running-turn", queuedTurns: [] } as SessionDetail;
    await mount(); await act(async () => surface.onComposerChange!("排队仍然可见"));
    await act(async () => surface.onSubmit()); await settle();
    expect(surface.composerValue).toBe("");
    expect(surface.followupQueue?.map(row => row.text)).toContain("排队仍然可见");
    expect(surface.messages.filter(row => row.role === "user")).toHaveLength(0);
    expect(client.getQueryData<SessionDetail>(["launcher-assistant", "detail", "session"])?.activeTurnId).toBe("running-turn");
  });

  it("preserves native streaming output when lagging ready detail lets a new message enter the queue", async () => {
    const fallback = invoke.getMockImplementation()!;
    let listener!: (event: unknown) => void;
    let sent = false;
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke, onSessionEvent: (callback: typeof listener) => { listener = callback; return () => {}; } });
    invoke.mockImplementation(async request => {
      if (request.operation === "send") { sent = true; return { accepted: true, status: "queued", turnId: "", queuedTurnId: "q-next", clientSubmissionId: request.requestId }; }
      if (request.operation === "detail" && sent) return new Promise(() => {});
      return fallback(request);
    });
    await mount();
    await act(async () => listener({ type: "assistant_delta", sessionId: "session", turnId: "native-turn", at: 1,
      ledgerSeq: 5, deltaSeq: 1, deltaSeqFrom: 1, stage: "responding", done: false, updatedAt: "2026-11-06T02:00:00Z",
      turnItems: [{ version: 3, id: "answer-r1", itemId: "answer", sessionId: "session", turnId: "native-turn", type: "agent_message",
        phase: "final_answer", text: "已显示的实时正文", status: "running", revision: 1, sequence: 1 }] }));
    expect(surface.activeTurnMessage?.turnItems).toEqual([expect.objectContaining({ text: "已显示的实时正文" })]);
    await act(async () => surface.onComposerChange!("下一条消息"));
    await act(async () => surface.onSubmit()); await settle();
    expect(surface.activeTurnMessage?.turnItems).toEqual([expect.objectContaining({ text: "已显示的实时正文" })]);
  });

  it("applies stop's native detail immediately instead of waiting for another GET", async () => {
    const fallback = invoke.getMockImplementation()!;
    let stopped = false;
    invoke.mockImplementation(async request => {
      if (request.operation === "stop") { stopped = true; return { ...detail, currentPhase: "ready", status: "ready", activeTurnId: "", stopRequested: false,
        ledgerSeq: 2, lastTurnTerminalTurnId: "running-turn", lastTurnStatus: "stopped_by_user" }; }
      if (request.operation === "detail" && stopped) return new Promise(() => {});
      return fallback(request);
    });
    detail = { ...detail, currentPhase: "thinking", status: "running", activeTurnId: "running-turn", ledgerSeq: 1 } as SessionDetail;
    await mount(); await act(async () => surface.onStop!()); await settle();
    expect(client.getQueryData<SessionDetail>(["launcher-assistant", "detail", "session"])).toMatchObject({ status: "ready", stopRequested: false });
  });

  it("applies guidance's native message and preserves a newer draft while the control is pending", async () => {
    const fallback = invoke.getMockImplementation()!;
    let finish!: (value: SessionDetail) => void;
    let guided = false;
    invoke.mockImplementation(async request => {
      if (request.operation === "guidance") { guided = true; return new Promise(resolve => { finish = resolve; }); }
      if (request.operation === "detail" && guided) return new Promise(() => {});
      return fallback(request);
    });
    detail = { ...detail, currentPhase: "thinking", status: "running", activeTurnId: "running-turn" } as SessionDetail;
    await mount(); await act(async () => surface.onComposerChange!("原引导"));
    await act(async () => surface.onSafeGuidance!()); await settle();
    await act(async () => surface.onComposerChange!("下一条草稿"));
    await act(async () => finish({ ...detail, messages: [{ id: "guidance", role: "user", content: "原引导", timestamp: "" }] } as SessionDetail));
    await settle(); expect(surface.composerValue).toBe("下一条草稿");
    expect(surface.messages.map(row => row.content)).toContain("原引导");
  });

  it("restores reference-only sends and resolves a lost ACK by native readback without a second send", async () => {
    await mount();
    const reference = { kind: "message", referenceId: "message:m1", sourceSessionId: "source", sourceMessageId: "m1", quote: "原引用" };
    await act(async () => surface.onAddComposerReference!(reference));
    await act(async () => surface.onSubmit()); await settle();
    const original = calls("send")[0]; expect(original).toMatchObject({ references: [reference] });
    await destroy(); await mount();
    expect(surface.composerReferences).toEqual([reference]);
    expect(loadLauncherComposer("session", "embedded")?.outstanding?.requestId).toBe(original.requestId);
    expect(calls("send")).toHaveLength(1);
    detail = { ...detail, messages: [{ id: "m-native", role: "user", text: "", timestamp: "", metadata: { clientSubmissionId: original.requestId, turnId: "native-turn" } }] } as SessionDetail;
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "detail", "session"] }); }); await settle();
    expect(loadLauncherComposer("session", "embedded")?.outstanding).toBeNull();
    expect(surface.composerReferences).toEqual([]);
    expect(calls("send")).toHaveLength(1);
  });

  it("retains the original continuation ID and expected snapshot on explicit retry after a cold remount", async () => {
    detail = { ...detail, activeLeafId: "head-1", ledgerSeq: 12, lastTurnTerminalTurnId: "turn-1", lastTurnStatus: "stopped_by_user",
      terminalReason: "stopped_by_user", currentPhase: "ready", activeTurnId: "" } as SessionDetail;
    await mount(); await act(async () => surface.onContinueTurn!()); await settle();
    const original = calls("continue")[0]; expect(original).toBeDefined();
    await destroy();
    detail = { ...detail, activeLeafId: "head-2", ledgerSeq: 13, lastTurnTerminalTurnId: "turn-2" };
    await mount(); expect(calls("continue")).toHaveLength(1);
    await act(async () => surface.onContinueTurn!()); await settle();
    expect(calls("continue")).toEqual([original, original]);
  });

  it("retires a cold continuation from exact native acceptance without sending it again", async () => {
    detail = { ...detail, activeLeafId: "head-1", ledgerSeq: 12, lastTurnTerminalTurnId: "turn-1", terminalReason: "stopped_by_user", currentPhase: "ready" };
    await mount(); await act(async () => surface.onContinueTurn!()); await settle();
    const original = calls("continue")[0]; await destroy();
    detail = { ...detail, activeTurnId: "continued-turn", currentPhase: "thinking", activeTask: {
      metadata: { clientSubmissionId: original.requestId, turnId: "continued-turn" },
    } } as SessionDetail;
    await mount();
    expect(loadLauncherComposer("session", "embedded")?.continuation).toMatchObject({ requestId: original.requestId, accepted: true });
    expect(calls("continue")).toHaveLength(1);
    expect(document.body.textContent).not.toContain("尚未确认继续请求");
  });

  it("reads native acceptance before an explicit send retry and never resends a received request", async () => {
    await mount(); await act(async () => surface.onComposerChange!("原消息"));
    await act(async () => surface.onSubmit()); await settle();
    const original = calls("send")[0];
    detail = { ...detail, activeTask: { metadata: { clientSubmissionId: original.requestId, turnId: "accepted-turn" } } } as SessionDetail;
    await act(async () => surface.onSubmit()); await settle();
    expect(calls("send")).toHaveLength(1);
    expect(loadLauncherComposer("session", "embedded")?.outstanding).toBeNull();
  });

  it("coalesces repeated retry clicks while checking the same unconfirmed request", async () => {
    await mount(); await act(async () => surface.onComposerChange!("原消息"));
    await act(async () => surface.onSubmit()); await settle();
    const original = calls("send")[0];
    await act(async () => { surface.onSubmit(); surface.onSubmit(); }); await settle();
    expect(calls("send")).toEqual([original, original]);
  });

  it.each(["canonical", "active_task"])("replays the same original request when %s acceptance lacks the turn binding", async kind => {
    const fallback = invoke.getMockImplementation()!;
    invoke.mockImplementation(async request => {
      if (request.operation === "send" && calls("send").length > 1) return { accepted: true, turnId: "bound-turn" };
      return fallback(request);
    });
    await mount(); await act(async () => surface.onComposerChange!("原消息"));
    await act(async () => surface.onSubmit()); await settle();
    const original = calls("send")[0];
    detail = kind === "canonical" ? { ...detail, messages: [{ id: "native", role: "user", content: "原消息", timestamp: "",
      metadata: { clientSubmissionId: original.requestId } }] } as SessionDetail
      : { ...detail, activeTask: { metadata: { clientSubmissionId: original.requestId } } } as SessionDetail;
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "detail", "session"] }); }); await settle();
    await act(async () => surface.onSubmit()); await settle();
    expect(calls("send")).toEqual([original, original]);
    expect(loadLauncherComposer("session", "embedded")?.outstanding).toBeNull();
  });

  it("replays the original continuation when acceptance has not supplied a turn binding", async () => {
    const fallback = invoke.getMockImplementation()!;
    invoke.mockImplementation(async request => {
      if (request.operation === "continue" && calls("continue").length > 1) return { accepted: true, turnId: "continued-turn" };
      return fallback(request);
    });
    detail = { ...detail, activeLeafId: "head", ledgerSeq: 12, lastTurnTerminalTurnId: "stopped-turn",
      lastTurnStatus: "stopped_by_user", terminalReason: "stopped_by_user", currentPhase: "ready", activeTurnId: "" } as SessionDetail;
    await mount(); await act(async () => surface.onContinueTurn!()); await settle();
    const original = calls("continue")[0];
    detail = { ...detail, activeTask: { metadata: { clientSubmissionId: original.requestId } } } as SessionDetail;
    await act(async () => { await client.invalidateQueries({ queryKey: ["launcher-assistant", "detail", "session"] }); }); await settle();
    await act(async () => surface.onContinueTurn!()); await settle();
    expect(calls("continue")).toEqual([original, original]);
    expect(loadLauncherComposer("session", "embedded")?.continuation?.accepted).toBe(true);
  });

  it("blocks a new write and explains when durable recovery cannot be saved", async () => {
    await mount();
    const storage = localStorage;
    vi.stubGlobal("localStorage", { getItem: storage.getItem.bind(storage), setItem: () => { throw new Error("quota"); } });
    await act(async () => surface.onComposerChange!("保留这条消息"));
    await act(async () => surface.onSubmit()); await settle();
    expect(calls("send")).toEqual([]);
    expect(document.body.textContent).toContain("恢复记录未能保存");
    expect(surface.composerValue).toBe("保留这条消息");
  });

  it("keeps the save failure visible when a larger new snapshot is rejected but rollback succeeds", async () => {
    await mount();
    await act(async () => surface.onComposerChange!("保留这条消息"));
    const storage = localStorage;
    const maxChars = Math.max(...Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index)!)!.length));
    // A full quota can still accept the smaller, previously persisted snapshot.
    const setItem = vi.fn((key: string, value: string) => {
      if (value.length > maxChars) throw new Error("quota");
      storage.setItem(key, value);
    });
    vi.stubGlobal("localStorage", { getItem: storage.getItem.bind(storage), setItem });
    await act(async () => surface.onSubmit()); await settle();
    expect(setItem).toHaveBeenCalledTimes(2);
    expect(JSON.parse(setItem.mock.calls[0][1]).snapshot.outstanding).not.toBeNull();
    expect(JSON.parse(setItem.mock.calls[1][1]).snapshot.outstanding).toBeNull();
    expect(loadLauncherComposer("session", "embedded")).toMatchObject({ draft: "保留这条消息", outstanding: null });
    expect(calls("send")).toEqual([]);
    expect(document.body.textContent).toContain("恢复记录未能保存");
    expect(surface.composerValue).toBe("保留这条消息");
  });
});
