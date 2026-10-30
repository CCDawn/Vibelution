// @vitest-environment happy-dom
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import type { SessionDetail, SessionToolApprovalRequest } from "../../api/types";
import { launcherAssistantActivity, launcherAssistantPollInterval, launcherAssistantSubmission, launcherDispatchLabel, launcherAssistantQueueReadback, launcherAssistantQueueLabel, launcherAssistantRequestReadback } from "./launcherAssistantModel";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";

const bridge = vi.hoisted(() => ({
  getLauncherAssistantStatus: vi.fn(), getLauncherAssistantDetail: vi.fn(), getLauncherAssistantDispatches: vi.fn(),
  hideLauncherAssistant: vi.fn(), sendLauncherAssistantMessage: vi.fn(), setLauncherAssistantExpanded: vi.fn(),
  openLauncherFromAssistant: vi.fn(),
  launcherConversationApi: { cacheKey: "launcher-test" },
  getLauncherAssistantApprovals: vi.fn(), resolveLauncherAssistantApproval: vi.fn(),
  stopLauncherAssistantTurn: vi.fn(), continueLauncherAssistantTurn: vi.fn(),
}));
vi.mock("../../api/launcherAssistant", () => bridge);
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
let character: { characterId: string; name: string } | undefined;
vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: (props: typeof character) => { character = props; return null; } }));
let conversation: ConversationViewProps | undefined;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => { conversation = props; return null; },
}));
let root: Root | undefined;
let container: HTMLDivElement | undefined;
let client: QueryClient | undefined;
beforeAll(() => vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true));
afterAll(() => vi.unstubAllGlobals());
afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  root = undefined;
  container?.remove();
  client?.clear();
  conversation = undefined;
  vi.clearAllMocks();
});

async function renderAssistant(initialDetail?: Record<string, unknown>, initialStatus?: Record<string, unknown>, statusRequest?: () => Promise<unknown>) {
  if (statusRequest) bridge.getLauncherAssistantStatus.mockImplementation(statusRequest);
  else bridge.getLauncherAssistantStatus.mockResolvedValue(initialStatus ?? { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" } });
  bridge.getLauncherAssistantDetail.mockResolvedValue(initialDetail ?? { id: "s", status: "ready", messages: [], defaultFileContext: "" });
  bridge.getLauncherAssistantDispatches.mockResolvedValue([]);
  bridge.getLauncherAssistantApprovals.mockResolvedValue([]);
  bridge.setLauncherAssistantExpanded.mockResolvedValue(undefined);
  bridge.hideLauncherAssistant.mockResolvedValue(undefined);
  bridge.openLauncherFromAssistant.mockResolvedValue({ opened: true });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  await act(async () => {
    root?.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantRoute, { key: "pet" })));
    await new Promise(resolve => setTimeout(resolve, 10));
  });
  await settle();
}
async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
}
async function click(label: string) {
  await act(async () => {
    const button = container?.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)
      ?? [...(container?.querySelectorAll<HTMLButtonElement>("button") ?? [])].find(node => node.textContent === label);
    expect(button).toBeTruthy();
    button?.click();
  });
  await settle();
}
async function showConversation() {
  await act(async () => root?.render(createElement(QueryClientProvider, { client: client! }, createElement(LauncherAssistantRoute, { embedded: true, key: "conversation" }))));
  await settle(); await settle();
}
async function showPet() {
  conversation = undefined;
  await act(async () => root?.render(createElement(QueryClientProvider, { client: client! }, createElement(LauncherAssistantRoute, { key: "pet" }))));
  await settle(); await settle();
}
async function pollCycle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
  await settle();
}
function changedAppearance() {
  bridge.getLauncherAssistantStatus.mockResolvedValue({ assistant: { agentId: "a", directSessionId: "s", displayName: "自动生效" }, settings: {
    ok: true, displayName: "自动生效", modelId: "m", preferences: { characterId: "xiaoluo", showStatus: false, showTitles: true, showCompletion: false, idleMessage: "休息中" },
  } });
}

describe("Launcher assistant state", () => {
  it("passes persisted provider failures to the shared conversation error panel", async () => {
    const lastTurnError = {
      message: "模型服务请求失败", errorType: "provider_protocol_error",
      providerErrorType: "insufficient_balance_error", providerErrorMessage: "Insufficient Balance",
      provider: "deepseek", recoverable: false, timestamp: "2026-10-25T13:32:21Z", turnId: "failed-turn",
    };
    await renderAssistant({ id: "s", status: "ready", messages: [], lastTurnError });
    await showConversation();
    expect(conversation?.turnError).toEqual(lastTurnError);
    expect(bridge.sendLauncherAssistantMessage).not.toHaveBeenCalled();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", messages: [], lastTurnError: null });
    await click("刷新");
    expect(conversation?.turnError).toBeNull();
  });

  it("reads its own collapsed session once for recovery and does not poll an idle session", async () => {
    await renderAssistant();
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(1);
    expect(bridge.getLauncherAssistantApprovals).not.toHaveBeenCalled();
    expect(bridge.getLauncherAssistantDispatches).not.toHaveBeenCalled();
    await pollCycle();
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(1);
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(1);
  });

  it("recovers a collapsed active session, applies terminal appearance and stops idle polling", async () => {
    await renderAssistant({ id: "s", status: "running", activeTurnId: "recovered", messages: [] });
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(1);
    changedAppearance();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "recovered", terminalReason: "success", messages: [] });
    await pollCycle();
    expect(character).toMatchObject({ characterId: "xiaoluo", name: "自动生效" });
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(2);
    const settledReads = bridge.getLauncherAssistantDetail.mock.calls.length;
    await pollCycle();
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(settledReads);
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(2);
    expect(bridge.getLauncherAssistantApprovals).not.toHaveBeenCalled();
    expect(bridge.getLauncherAssistantDispatches).not.toHaveBeenCalled();
  }, 10_000);

  it("keeps an accepted turn observed after natural collapse and refreshes appearance at terminal", async () => {
    await renderAssistant(); await showConversation();
    bridge.sendLauncherAssistantMessage.mockResolvedValueOnce({ turnId: "settings-turn" });
    await act(async () => conversation?.onComposerChange("改成小洛"));
    await act(async () => conversation?.onSubmit());
    await showPet();
    const statusReads = bridge.getLauncherAssistantStatus.mock.calls.length;
    const approvalReads = bridge.getLauncherAssistantApprovals.mock.calls.length;
    const dispatchReads = bridge.getLauncherAssistantDispatches.mock.calls.length;
    changedAppearance();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "settings-turn", terminalReason: "success", messages: [] });
    await pollCycle();
    expect(container?.querySelector('[data-expanded="false"]')).toBeTruthy();
    expect(character).toMatchObject({ characterId: "xiaoluo", name: "自动生效" });
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(statusReads + 1);
    expect(bridge.getLauncherAssistantApprovals).toHaveBeenCalledTimes(approvalReads);
    expect(bridge.getLauncherAssistantDispatches).toHaveBeenCalledTimes(dispatchReads);
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
  });

  it.each(["", "新的 B"])("observes an ACK arriving after collapse through its original request and preserves draft %s", async newDraft => {
    await renderAssistant(); await showConversation();
    let acknowledge!: (value: unknown) => void;
    bridge.sendLauncherAssistantMessage.mockImplementationOnce(() => new Promise(done => { acknowledge = done; }));
    await act(async () => conversation?.onComposerChange("请求 A"));
    await act(async () => conversation?.onSubmit());
    const requestId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    if (newDraft) await act(async () => conversation?.onComposerChange(newDraft));
    await showPet();
    await act(async () => acknowledge({ turnId: "late-ack" }));
    changedAppearance();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "late-ack", terminalReason: "success",
      messages: [{ role: "user", content: "请求 A", metadata: { clientSubmissionId: requestId, turnId: "late-ack" } }] });
    await pollCycle();
    expect(character).toMatchObject({ characterId: "xiaoluo", name: "自动生效" });
    expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ draft: newDraft, outstanding: null });
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
  });

  it("keeps exact same-epoch native acceptance authoritative when the original send later rejects", async () => {
    await renderAssistant(); await showConversation();
    let rejectSend!: (error: Error) => void;
    bridge.sendLauncherAssistantMessage.mockImplementationOnce(() => new Promise((_done, reject) => { rejectSend = reject; }));
    await act(async () => conversation?.onComposerChange("请求 A"));
    await act(async () => conversation?.onSubmit());
    const requestId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    await act(async () => conversation?.onComposerChange("新的 B"));
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "native-A", terminalReason: "success",
      messages: [{ role: "user", metadata: { clientSubmissionId: requestId, turnId: "native-A" } }] });
    await pollCycle();
    expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ draft: "新的 B", outstanding: null });
    await act(async () => rejectSend(new Error("late ACK lost")));
    await settle();
    expect(conversation?.composerValue).toBe("新的 B");
    expect(conversation?.composerError).toBe("");
    expect(conversation?.composerDisabled).toBe(false);
    expect(conversation?.composerPending).toBe(false);
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
  });

  it.each(["reject", "stale queued ACK"])("does not let old %s clear or overwrite a newer pending send after native readback", async lateResult => {
    await renderAssistant(); await showConversation();
    let finishA!: (value: unknown) => void, rejectA!: (error: Error) => void, finishB!: (value: unknown) => void;
    bridge.sendLauncherAssistantMessage.mockImplementationOnce(() => new Promise((done, reject) => { finishA = done; rejectA = reject; }))
      .mockImplementationOnce(() => new Promise(done => { finishB = done; }));
    await act(async () => conversation?.onComposerChange("请求 A"));
    await act(async () => conversation?.onSubmit());
    const originalId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    await act(async () => conversation?.onComposerChange("新的 B"));
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "native-A", terminalReason: "success",
      messages: [{ role: "user", metadata: { clientSubmissionId: originalId, turnId: "native-A" } }] });
    await pollCycle();
    expect(conversation?.composerDisabled).toBe(false);
    await act(async () => conversation?.onSubmit());
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(2);
    const nextId = bridge.sendLauncherAssistantMessage.mock.calls[1][1];
    expect(nextId).not.toBe(originalId);
    await act(async () => {
      if (lateResult === "reject") rejectA(new Error("late A failure"));
      else finishA({ turnId: "", queuedTurnId: "stale-queue-A", clientSubmissionId: originalId });
    });
    await settle();
    expect(conversation?.composerValue).toBe("新的 B");
    expect(conversation?.composerError).toBe("");
    expect(conversation?.composerPending).toBe(true);
    expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ draft: "新的 B", outstanding: { requestId: nextId }, queuedAcceptance: null });
    await act(async () => finishB({ turnId: "native-B" }));
    await settle();
    expect(conversation?.composerPending).toBe(false);
    expect(conversation?.composerDisabled).toBe(false);
    expect(conversation?.composerValue).toBe("");
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(2);
  });

  it("reads back an unknown continuation after collapse without another request or losing a new draft", async () => {
    await renderAssistant();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", agentId: "a", activeLeafId: "head-a", ledgerSeq: 12, lastTurnTerminalTurnId: "turn-a",
      lastTurnStatus: "stopped_by_user", terminalReason: "stopped_by_user", currentPhase: "ready", activeTurnId: "", messages: [] });
    await showConversation();
    bridge.continueLauncherAssistantTurn.mockRejectedValueOnce(new Error("ACK unknown"));
    await act(async () => conversation?.onContinueTurn?.());
    const requestId = bridge.continueLauncherAssistantTurn.mock.calls[0][1];
    await act(async () => conversation?.onComposerChange("新的 B"));
    await showPet();
    changedAppearance();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "continued-turn", terminalReason: "success",
      messages: [{ role: "user", metadata: { clientSubmissionId: requestId, turnId: "continued-turn" } }] });
    await pollCycle();
    expect(character).toMatchObject({ characterId: "xiaoluo", name: "自动生效" });
    expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ draft: "新的 B", continuation: { requestId, accepted: true } });
    expect(bridge.continueLauncherAssistantTurn).toHaveBeenCalledTimes(1);
    expect(bridge.sendLauncherAssistantMessage).not.toHaveBeenCalled();
  });

  it("stops its own active-session polling while the window is hidden", async () => {
    await renderAssistant({ id: "s", status: "running", activeTurnId: "active", messages: [] });
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    try {
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
      await settle();
      const reads = bridge.getLauncherAssistantDetail.mock.calls.length;
      await pollCycle();
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads);
    } finally { visibility.mockRestore(); }
  });

  it("follows an accepted queue through collapsed admission and terminal without using its queue ID as a Turn", async () => {
    await renderAssistant(); await showConversation();
    bridge.sendLauncherAssistantMessage.mockImplementationOnce(async (_message: string, clientSubmissionId: string) => ({ turnId: "", queuedTurnId: "queue-only", clientSubmissionId }));
    await act(async () => conversation?.onComposerChange("排队修改外观"));
    await act(async () => conversation?.onSubmit());
    const requestId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    await showPet();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", messages: [], queuedTurns: [{ id: "queue-only", clientSubmissionId: requestId, status: "starting" }] });
    await pollCycle();
    expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ acceptedTurnId: "", queuedAcceptance: { id: "queue-only", observed: true } });
    changedAppearance();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "native-admission", terminalReason: "success", queuedTurns: [],
      messages: [{ role: "user", metadata: { clientSubmissionId: requestId, turnId: "native-admission" } }] });
    await pollCycle();
    expect(character).toMatchObject({ characterId: "xiaoluo", name: "自动生效" });
    expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ queuedAcceptance: null });
    const reads = bridge.getLauncherAssistantDetail.mock.calls.length;
    await pollCycle();
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads);
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
  }, 12_000);

  it("requires exact original-request evidence past stale terminal and preserves queue/Turn identity", () => {
    const unrelated = { status: "ready", lastTurnTerminalTurnId: "old", terminalReason: "success", messages: [{ role: "user", metadata: { clientSubmissionId: "other", turnId: "old" } }] } as unknown as SessionDetail;
    expect(launcherAssistantRequestReadback(unrelated, "original")).toBeNull();
    expect(launcherAssistantPollInterval(true, unrelated, "", null, ["original"])).toBe(2_000);
    expect(launcherAssistantPollInterval(false, unrelated, "", null, ["original"])).toBe(false);
    const terminal = { ...unrelated, lastTurnTerminalTurnId: "matching", messages: [{ role: "user", metadata: { clientSubmissionId: "original", turnId: "matching" } }] } as unknown as SessionDetail;
    expect(launcherAssistantRequestReadback(terminal, "original")).toEqual({ turnId: "matching", queuedAcceptance: null });
    expect(launcherAssistantPollInterval(true, terminal, "", null, ["original"])).toBe(false);
    const queued = { ...unrelated, queuedTurns: [{ id: "queue-only", clientSubmissionId: "original", status: "paused" }] } as unknown as SessionDetail;
    expect(launcherAssistantRequestReadback(queued, "original")).toEqual({ turnId: "", queuedAcceptance: { id: "queue-only", clientSubmissionId: "original", observed: true } });
    expect(launcherAssistantPollInterval(true, queued, "", null, ["original"])).toBe(false);
  });

  it("retains an unconfirmed message and request ID instead of inventing another request", () => {
    const createId = vi.fn(() => "id-1");
    const first = launcherAssistantSubmission(null, " hello ", createId);
    expect(first).toEqual({ message: "hello", requestId: "id-1", draftSnapshot: " hello " });
    expect(launcherAssistantSubmission(first, "changed draft", createId)).toBe(first);
    expect(createId).toHaveBeenCalledTimes(1);
    expect(launcherAssistantSubmission(null, "   ", createId)).toBeNull();
  });

  it("polls only a visible initial or active native session", () => {
    expect(launcherAssistantPollInterval(false, { status: "running" })).toBe(false);
    expect(launcherAssistantPollInterval(true)).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "running" })).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "queued" })).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "ready" })).toBe(false);
  });

  it("does not animate ready as successful completion", () => {
    expect(launcherAssistantActivity({ status: "ready" })).toEqual({ tone: "idle", animationState: "idle" });
    expect(launcherAssistantActivity({ status: "running" }).tone).toBe("running");
    expect(launcherAssistantActivity({ status: "paused" }).tone).toBe("approval");
    expect(launcherAssistantActivity({ status: "ready", terminalReason: "error" }).tone).toBe("error");
  });

  it("waits past stale ready and the previous terminal until the accepted turn settles", () => {
    expect(launcherAssistantPollInterval(true, { status: "ready", lastTurnTerminalTurnId: "old" }, "new")).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "running", activeTurnId: "new" }, "new")).toBe(2_000);
    expect(launcherAssistantPollInterval(false, { status: "running" }, "new")).toBe(false);
    expect(launcherAssistantPollInterval(true, { status: "ready", lastTurnTerminalTurnId: "new", terminalReason: "success" }, "new")).toBe(false);
  });

  it("labels raw native receipts without inventing business acceptance", () => {
    expect(launcherDispatchLabel({ dispatchId: "d", receipt: { status: "ready" } }, "zh")).toBe("原生任务状态: ready");
    expect(launcherDispatchLabel({ dispatchId: "d", lastError: { code: "unavailable" } }, "zh")).toBe("回执暂不可用");
  });

  it("waits for accepted native queue readback, then follows queued status instead of idle polling", () => {
    const receipt = { id: "q", clientSubmissionId: "r", observed: false };
    expect(launcherAssistantPollInterval(true, { status: "ready" }, "", receipt)).toBe(2_000);
    const readback = launcherAssistantQueueReadback({ messages: [], queuedTurns: [{ id: "q", clientSubmissionId: "r", status: "paused" }] } as unknown as SessionDetail, receipt);
    expect(readback.receipt?.observed).toBe(true);
    for (const status of ["paused", "blocked"]) {
      expect(launcherAssistantPollInterval(true, { status: "ready", queuedTurns: [{ id: "q", clientSubmissionId: "r", status }] }, "", readback.receipt)).toBe(false);
      expect(launcherAssistantQueueLabel(status, "zh")).not.toContain("完成");
    }
    expect(launcherAssistantPollInterval(true, { status: "ready", queuedTurns: [{ id: "q", status: "queued" }] }, "", readback.receipt)).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "ready", queuedTurns: [{ id: "q", status: "starting" }] }, "", readback.receipt)).toBe(2_000);
    expect(launcherAssistantPollInterval(false, { status: "ready" }, "", receipt)).toBe(false);
    const removed = launcherAssistantQueueReadback({ messages: [], queuedTurns: [] } as unknown as SessionDetail, readback.receipt);
    expect(removed).toMatchObject({ removed: true, admittedTurnId: "" });
    expect(launcherAssistantPollInterval(true, { status: "ready" }, "", removed.receipt)).toBe(false);
  });

  it("correlates queue admission with canonical submission metadata rather than queue ID or an unrelated turn", () => {
    const receipt = { id: "q", clientSubmissionId: "r", observed: false };
    const source = { messages: [{ role: "user", metadata: { clientSubmissionId: "other", turnId: "unrelated" } }], queuedTurns: [] } as unknown as SessionDetail;
    expect(launcherAssistantQueueReadback(source, receipt)).toMatchObject({ receipt, admittedTurnId: "", removed: false });
    source.messages[0].metadata = { clientSubmissionId: "r", turnId: "native-turn" };
    expect(launcherAssistantQueueReadback(source, receipt)).toEqual({ receipt: null, admittedTurnId: "native-turn", removed: false });
  });
});

describe("Launcher native turn controls", () => {
  it("keeps a new draft while an admitted queue send is awaiting its acknowledgement", async () => {
    await renderAssistant();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", agentId: "a", currentPhase: "thinking", activeTurnId: "running", messages: [] });
    let resolve!: (value: unknown) => void;
    bridge.sendLauncherAssistantMessage.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    await showConversation();
    await act(async () => conversation?.onComposerChange("排队的 A"));
    await act(async () => conversation?.onSubmit());
    await act(async () => conversation?.onComposerChange("稍后发送的 B"));
    const requestId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    await act(async () => resolve({ turnId: "", queuedTurnId: "q", clientSubmissionId: requestId }));
    expect(conversation?.composerValue).toBe("稍后发送的 B");
    expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ draft: "稍后发送的 B", outstanding: null });
  });

  it("reconciles an unknown continuation with the original request even after the detail head changes", async () => {
    await renderAssistant();
    const stopped = { id: "s", agentId: "a", activeLeafId: "head-a", ledgerSeq: 12, lastTurnTerminalTurnId: "turn-a",
      lastTurnStatus: "stopped_by_user", terminalReason: "stopped_by_user", currentPhase: "ready", activeTurnId: "", messages: [] };
    bridge.getLauncherAssistantDetail.mockResolvedValue(stopped);
    bridge.continueLauncherAssistantTurn.mockRejectedValueOnce(new Error("ack lost")).mockResolvedValueOnce({ turnId: "native-confirmed" });
    await showConversation();
    await act(async () => conversation?.onContinueTurn?.());
    bridge.getLauncherAssistantDetail.mockResolvedValue({ ...stopped, activeLeafId: "head-b", ledgerSeq: 20, lastTurnTerminalTurnId: "turn-b" });
    await click("刷新");
    await act(async () => conversation?.onContinueTurn?.());
    expect(bridge.continueLauncherAssistantTurn.mock.calls).toHaveLength(2);
    expect(bridge.continueLauncherAssistantTurn.mock.calls[1]).toEqual(bridge.continueLauncherAssistantTurn.mock.calls[0]);
  });

  it("uses native submission evidence to confirm a lost continuation without another request", async () => {
    await renderAssistant();
    const stopped = { id: "s", agentId: "a", activeLeafId: "head-a", ledgerSeq: 12, lastTurnTerminalTurnId: "turn-a",
      lastTurnStatus: "stopped_by_user", terminalReason: "stopped_by_user", currentPhase: "ready", activeTurnId: "", messages: [] };
    bridge.getLauncherAssistantDetail.mockResolvedValue(stopped);
    bridge.continueLauncherAssistantTurn.mockRejectedValueOnce(new Error("ack lost"));
    await showConversation();
    await act(async () => conversation?.onContinueTurn?.());
    const requestId = bridge.continueLauncherAssistantTurn.mock.calls[0][1];
    bridge.getLauncherAssistantDetail.mockResolvedValue({ ...stopped, activeLeafId: "head-b", ledgerSeq: 20,
      lastTurnTerminalTurnId: "turn-b", terminalReason: "success",
      messages: [{ role: "user", metadata: { clientSubmissionId: requestId, turnId: "turn-b" } }] });
    await click("刷新");
    await settle();
    expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ continuation: { requestId, accepted: true } });
    expect(bridge.continueLauncherAssistantTurn).toHaveBeenCalledTimes(1);
  });

  it("does not retry an unknown send while native stop acknowledgement is pending", async () => {
    await renderAssistant();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", agentId: "a", currentPhase: "thinking", activeTurnId: "running", messages: [] });
    bridge.sendLauncherAssistantMessage.mockRejectedValueOnce(new Error("ack lost"));
    let resolve!: (value: unknown) => void;
    bridge.stopLauncherAssistantTurn.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    await showConversation();
    await act(async () => conversation?.onComposerChange("A"));
    await act(async () => conversation?.onSubmit());
    await act(async () => conversation?.onStop?.());
    const retry = Array.from(container?.querySelectorAll("button") || []).find(button => button.textContent === "重试");
    expect(retry?.disabled).toBe(true);
    await act(async () => conversation?.onSubmit());
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
    await act(async () => resolve({ id: "s", stopRequested: true }));
  });
  it("stops the current native turn and never sends a synthetic chat message", async () => {
    await renderAssistant();
    const active = { id: "s", agentId: "a", status: "running", currentPhase: "thinking", activeTurnId: "native-running", messages: [] };
    bridge.getLauncherAssistantDetail.mockResolvedValue(active);
    bridge.stopLauncherAssistantTurn.mockResolvedValue({ id: "s", stopRequested: true });
    await showConversation();
    expect(conversation?.composerActionMode).toBe("stop");
    await act(async () => conversation?.onStop?.());
    expect(bridge.stopLauncherAssistantTurn).toHaveBeenCalledExactlyOnceWith("s", "native-running");
    expect(bridge.sendLauncherAssistantMessage).not.toHaveBeenCalled();
  });

  it("reuses one continuation ID after unknown acknowledgement and preserves a new draft", async () => {
    await renderAssistant();
    const stopped = { id: "s", agentId: "a", activeLeafId: "head-a", ledgerSeq: 12,
      lastTurnTerminalTurnId: "turn-a", lastTurnStatus: "stopped_by_user", terminalReason: "stopped_by_user",
      currentPhase: "ready", activeTurnId: "", messages: [] };
    bridge.getLauncherAssistantDetail.mockResolvedValue(stopped);
    bridge.continueLauncherAssistantTurn.mockRejectedValueOnce(new Error("ack lost"))
      .mockResolvedValueOnce({ turnId: "new-turn" });
    await showConversation();
    expect(conversation?.composerActionMode).toBe("continue");
    await act(async () => conversation?.onContinueTurn?.());
    await act(async () => conversation?.onContinueTurn?.());
    const calls = bridge.continueLauncherAssistantTurn.mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0]).toEqual(calls[1]);
    expect(calls[0][0]).toEqual({ turnId: "turn-a", headId: "head-a", ledgerSeq: 12, agentId: "a" });
    expect(bridge.sendLauncherAssistantMessage).not.toHaveBeenCalled();
    await act(async () => conversation?.onComposerChange("新的用户草稿"));
    expect(conversation?.composerActionMode).toBe("send");
    expect(conversation?.composerValue).toBe("新的用户草稿");
  });
});

describe("Launcher assistant route lifecycle", () => {
  it("shows a status read error despite a cached preference hiding ordinary pet status", async () => {
    await renderAssistant(undefined, { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
      settings: { ok: true, displayName: "助理", modelId: "m", preferences: {
        characterId: "dafeiyu", showStatus: false, showTitles: true, showCompletion: true, idleMessage: "",
      } } });
    expect(container?.querySelector('[role="status"]')?.hasAttribute("hidden")).toBe(true);
    bridge.getLauncherAssistantStatus.mockRejectedValueOnce(new Error("status unavailable"));
    await act(async () => { await client?.refetchQueries({ queryKey: ["launcher-assistant", "status"], exact: true }); });
    await settle();
    const status = container?.querySelector('[role="status"]');
    expect(status?.hasAttribute("hidden")).toBe(false);
    expect(status?.textContent).toContain("个人助理暂不可用");
    await click("打开 Launcher");
    expect(bridge.openLauncherFromAssistant).toHaveBeenCalledOnce();
    expect(bridge.setLauncherAssistantExpanded).not.toHaveBeenCalled();
  });

  it.each(["pending", "error"] as const)("keeps the pet Launcher entry usable while native identity is %s", async state => {
    let resolveStatus!: (value: unknown) => void;
    const pending = new Promise(resolve => { resolveStatus = resolve; });
    await renderAssistant(undefined, undefined, () => state === "pending" ? pending : Promise.reject(new Error("native unavailable")));
    const pet = container!.querySelector<HTMLButtonElement>('button[aria-label="打开 Launcher"]');
    expect(pet).toBeTruthy();
    expect(pet?.disabled).toBe(false);
    expect(bridge.getLauncherAssistantDetail).not.toHaveBeenCalled();
    await act(async () => pet?.click());
    expect(bridge.openLauncherFromAssistant).toHaveBeenCalledOnce();
    expect(bridge.setLauncherAssistantExpanded).not.toHaveBeenCalled();
    if (state === "pending") await act(async () => resolveStatus({ assistant: { agentId: "a", directSessionId: "s", displayName: "助理" } }));
  });

  it("opens the native transcript in the Launcher and keeps the pet independently hideable", async () => {
    await renderAssistant();
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(1);
    expect(conversation).toBeUndefined();
    await showConversation();
    expect(bridge.setLauncherAssistantExpanded).not.toHaveBeenCalled();
    expect(conversation?.messages).toEqual([]);
    expect(conversation?.runtimeApi).toBe(bridge.launcherConversationApi);
    expect(bridge.stopLauncherAssistantTurn).not.toHaveBeenCalled();
    await showPet();
    await click("隐藏个人助理");
    expect(bridge.hideLauncherAssistant).toHaveBeenCalledTimes(1);
  });

  it("opens Launcher directly, coalesces clicks and remains usable after a failed or cancelled request", async () => {
    await renderAssistant();
    let rejectOpen!: (error: Error) => void;
    bridge.openLauncherFromAssistant.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOpen = reject; }));
    const pet = container!.querySelector<HTMLButtonElement>('button[aria-label="打开 Launcher"]')!;
    await act(async () => { pet.click(); pet.click(); });
    expect(bridge.openLauncherFromAssistant).toHaveBeenCalledTimes(1);
    expect(bridge.setLauncherAssistantExpanded).not.toHaveBeenCalled();
    expect(conversation).toBeUndefined();
    await act(async () => rejectOpen(new Error("无法打开 Launcher")));
    await settle();
    expect(container?.textContent).toContain("无法打开 Launcher");
    bridge.openLauncherFromAssistant.mockResolvedValueOnce({ opened: false });
    await act(async () => pet.click()); await settle();
    expect(bridge.openLauncherFromAssistant).toHaveBeenCalledTimes(2);
    expect(container?.textContent).not.toContain("无法打开 Launcher");
    await act(async () => pet.click()); await settle();
    expect(bridge.openLauncherFromAssistant).toHaveBeenCalledTimes(3);
    expect(bridge.setLauncherAssistantExpanded).not.toHaveBeenCalled();
    expect(conversation).toBeUndefined();
  });

  it("moves the pet on drag without interpreting the release as a Launcher click", async () => {
    const native = { beginDesktopPetWindowDrag: vi.fn(), moveDesktopPetWindowDrag: vi.fn(), endDesktopPetWindowDrag: vi.fn() };
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, "vibelutionLauncher");
    Object.defineProperty(globalThis, "vibelutionLauncher", { value: native, configurable: true });
    try {
      await renderAssistant();
      const pet = container!.querySelector<HTMLButtonElement>('button[aria-label="打开 Launcher"]')!;
      pet.setPointerCapture = vi.fn();
      await act(async () => {
        pet.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerId: 1, screenX: 10, screenY: 10 }));
        pet.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 1, screenX: 20, screenY: 10 }));
        pet.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, screenX: 20, screenY: 10 }));
        pet.click();
      });
      expect(native.beginDesktopPetWindowDrag).toHaveBeenCalledWith({ screenX: 10, screenY: 10 });
      expect(native.moveDesktopPetWindowDrag).toHaveBeenCalledWith({ screenX: 20, screenY: 10 });
      expect(native.endDesktopPetWindowDrag).toHaveBeenCalledOnce();
      expect(bridge.openLauncherFromAssistant).not.toHaveBeenCalled();
      expect(bridge.setLauncherAssistantExpanded).not.toHaveBeenCalled();
    } finally {
      if (descriptor) Object.defineProperty(globalThis, "vibelutionLauncher", descriptor);
      else delete (globalThis as { vibelutionLauncher?: unknown }).vibelutionLauncher;
    }
  });

  it("keeps a failed draft and retries exactly the same request", async () => {
    bridge.sendLauncherAssistantMessage.mockRejectedValueOnce(new Error("unknown delivery")).mockResolvedValueOnce({ turnId: "t" });
    await renderAssistant();
    await showConversation();
    await act(async () => conversation?.onComposerChange("hello"));
    await act(async () => conversation?.onSubmit());
    expect(conversation?.composerValue).toBe("hello");
    expect(conversation?.composerDisabled).toBe(true);
    const first = bridge.sendLauncherAssistantMessage.mock.calls[0];
    await act(async () => conversation?.onSubmit());
    expect(bridge.sendLauncherAssistantMessage.mock.calls[1]).toEqual(first);
    expect(conversation?.composerValue).toBe("");
  });

  it("ignores delivery results belonging to a collapsed view and preserves the retry ID", async () => {
    let resolveSend!: () => void;
    bridge.sendLauncherAssistantMessage.mockImplementationOnce(() => new Promise<void>(resolve => { resolveSend = resolve; }));
    await renderAssistant();
    await showConversation();
    await act(async () => conversation?.onComposerChange("hello"));
    await act(async () => conversation?.onSubmit());
    const first = bridge.sendLauncherAssistantMessage.mock.calls[0];
    await showPet();
    await act(async () => resolveSend());
    await showConversation();
    expect(conversation?.composerValue).toBe("hello");
    expect(conversation?.composerError).toContain("尚未确认");
    await act(async () => conversation?.onSubmit());
    expect(bridge.sendLauncherAssistantMessage.mock.calls[1]).toEqual(first);
  });

  it("keeps reading an accepted turn after an immediately stale ready response, then stops at its terminal", async () => {
    bridge.sendLauncherAssistantMessage.mockResolvedValueOnce({ turnId: "turn-new" });
    await renderAssistant();
    await showConversation();
    await act(async () => conversation?.onComposerChange("hello"));
    await act(async () => conversation?.onSubmit());
    await settle();
    const initialReads = bridge.getLauncherAssistantDetail.mock.calls.length;
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "turn-new", terminalReason: "success", messages: [{ id: "answer", role: "assistant", content: "done" }] });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    await settle();
    expect(bridge.getLauncherAssistantDetail.mock.calls.length).toBeGreaterThan(initialReads);
    expect(conversation?.messages).toEqual([expect.objectContaining({ id: "answer" })]);
    const terminalReads = bridge.getLauncherAssistantDetail.mock.calls.length;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(terminalReads);
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
  });

  it("restores an unconfirmed draft after route unmount using the same window cache", async () => {
    bridge.sendLauncherAssistantMessage.mockRejectedValue(new Error("unknown"));
    await renderAssistant();
    await showConversation();
    await act(async () => conversation?.onComposerChange("keep me"));
    await act(async () => conversation?.onSubmit());
    const first = bridge.sendLauncherAssistantMessage.mock.calls[0];
    await act(async () => root?.unmount());
    root = createRoot(container!);
    await act(async () => root?.render(createElement(QueryClientProvider, { client: client! }, createElement(LauncherAssistantRoute, { key: "pet" }))));
    await settle();
    await showConversation();
    expect(conversation?.composerValue).toBe("keep me");
    await act(async () => conversation?.onSubmit());
    expect(bridge.sendLauncherAssistantMessage.mock.calls[1]).toEqual(first);
  });

  it("hands polling back to native activity after the accepted activeTurnId is visible", async () => {
    bridge.sendLauncherAssistantMessage.mockResolvedValueOnce({ turnId: "turn-visible" });
    await renderAssistant();
    await showConversation();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "running", activeTurnId: "turn-visible", messages: [] });
    await act(async () => conversation?.onComposerChange("hello"));
    await act(async () => conversation?.onSubmit());
    await settle();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "later-turn", terminalReason: "success", messages: [] });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    await settle();
    const idleReads = bridge.getLauncherAssistantDetail.mock.calls.length;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(idleReads);
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
  });

  it("accepts a busy-session queue receipt once, reads through stale ready and follows native admission to terminal", async () => {
    await renderAssistant();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "running", activeTurnId: "previous", messages: [], queuedTurns: [] });
    await showConversation();
    bridge.sendLauncherAssistantMessage.mockImplementationOnce(async (_message: string, requestId: string) => ({ turnId: "", queuedTurnId: "queue-1", clientSubmissionId: requestId }));
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", messages: [], queuedTurns: [] });
    await act(async () => conversation?.onComposerChange("queued hello"));
    await act(async () => conversation?.onSubmit());
    await settle();
    expect(conversation?.composerValue).toBe("");
    expect(conversation?.composerError).toBe("");
    expect(container?.textContent).toContain("已排队，正在读取原生队列");
    const requestId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", messages: [], queuedTurns: [{ id: "queue-1", clientSubmissionId: requestId, status: "queued" }] });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    await settle();
    expect(container?.querySelector("[data-launcher-assistant-queue]")?.textContent).toBe("已排队");
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", messages: [], queuedTurns: [{ id: "queue-1", clientSubmissionId: requestId, status: "starting" }] });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    await settle();
    expect(container?.querySelector("[data-launcher-assistant-queue]")?.textContent).toBe("排队消息正在入场");
    const message = { id: "native-user", role: "user", content: "queued hello", metadata: { clientSubmissionId: requestId, turnId: "admitted-turn" } };
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "running", activeTurnId: "admitted-turn", messages: [message], queuedTurns: [] });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    await settle();
    expect(container?.querySelector("[data-launcher-assistant-queue]")).toBeNull();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", terminalReason: "success", lastTurnTerminalTurnId: "admitted-turn", messages: [message], queuedTurns: [] });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    await settle();
    const terminalReads = bridge.getLauncherAssistantDetail.mock.calls.length;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(terminalReads);
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
  });

  it.each(["paused", "blocked"])("shows a native %s queue row without idle polling or treating removal as success", async queueStatus => {
    await renderAssistant();
    bridge.sendLauncherAssistantMessage.mockImplementationOnce(async (_message: string, requestId: string) => ({ turnId: "", queuedTurnId: "queue-held", clientSubmissionId: requestId }));
    await showConversation();
    await act(async () => conversation?.onComposerChange("held hello"));
    await act(async () => conversation?.onSubmit());
    const requestId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", terminalReason: "success", lastTurnTerminalTurnId: "previous-turn", messages: [], queuedTurns: [{ id: "queue-held", clientSubmissionId: requestId, status: queueStatus, lastError: queueStatus === "blocked" ? "需要修改" : "" }] });
    await click("刷新");
    expect(container?.querySelector("[data-launcher-assistant-queue]")?.textContent).toContain(launcherAssistantQueueLabel(queueStatus, "zh"));
    expect(container?.querySelector("header [role='status']")?.textContent).toBe(launcherAssistantQueueLabel(queueStatus, "zh"));
    const heldReads = bridge.getLauncherAssistantDetail.mock.calls.length;
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(heldReads);
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", messages: [], queuedTurns: [] });
    await click("刷新");
    expect(container?.querySelector("[data-launcher-assistant-queue]")?.textContent).toBe("排队消息已移除");
    expect(container?.querySelector("header [role='status']")?.textContent).toBe("排队消息已移除");
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
  });

  it("refreshes appearance from Launcher settings and honors hidden status/title preferences", async () => {
    await renderAssistant();
    bridge.getLauncherAssistantStatus.mockResolvedValue({ assistant: { agentId: "a", directSessionId: "s", displayName: "old" }, settings: {
      ok: true, displayName: "小洛", modelId: "m", preferences: { characterId: "xiaoluo", showStatus: false, showTitles: false, showCompletion: false, idleMessage: "休息中" },
    } });
    await showConversation();
    expect(conversation?.assistantDisplayName).toBe("小洛");
    await showPet();
    expect(container?.querySelector('[role="status"]')?.hasAttribute("hidden")).toBe(true);
    expect(character).toMatchObject({ characterId: "xiaoluo", name: "小洛" });
  });

  it.each([
    [{ status: "ready" }, "在这里陪你"],
    [{ status: "ready", terminalReason: "success" }, "在这里陪你"],
    [{ status: "ready", terminalReason: "error" }, "失败"],
    [{ status: "ready", terminalReason: "needs_continue" }, "待继续"],
    [{ status: "paused" }, "已暂停"],
    [{ status: "running" }, "进行中"],
    [{ status: "ready", terminalReason: "stopped_by_user" }, "已停止"],
  ])("shows the appropriate status for %o", async (state, expected) => {
    await renderAssistant({ id: "s", messages: [], ...state }, {
      assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
      settings: { ok: true, displayName: "助理", modelId: "m", preferences: {
        characterId: "xiaoluo", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在这里陪你",
      } },
    });
    expect(container?.querySelector('[role="status"]')?.textContent).toBe(expected);
  });

  it("refreshes settings after a successful Turn and then shows the new idle message", async () => {
    const preferences = { characterId: "xiaoluo", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "旧提示" };
    await renderAssistant({ id: "s", status: "running", activeTurnId: "settings-turn", messages: [] }, {
      assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
      settings: { ok: true, displayName: "助理", modelId: "m", preferences },
    });
    const statusReads = bridge.getLauncherAssistantStatus.mock.calls.length;
    bridge.getLauncherAssistantStatus.mockResolvedValue({ assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
      settings: { ok: true, displayName: "助理", modelId: "m", preferences: { ...preferences, idleMessage: "新提示" } } });
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", terminalReason: "success",
      lastTurnTerminalTurnId: "settings-turn", messages: [] });
    await act(async () => { await client?.refetchQueries({ queryKey: ["launcher-assistant", "detail", "s"] }); });
    await settle(); await settle();
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(statusReads + 1);
    expect(container?.querySelector('[role="status"]')?.textContent).toBe("新提示");
  });

  it("keeps the completion label when no idle message is configured", async () => {
    await renderAssistant({ id: "s", status: "ready", terminalReason: "success", messages: [] });
    expect(container?.querySelector('[role="status"]')?.textContent).toBe("已完成");
  });

  it("does not replace a pending approval with the idle message", async () => {
    await renderAssistant({ id: "s", status: "ready", terminalReason: "success", messages: [] }, {
      assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
      settings: { ok: true, displayName: "助理", modelId: "m", preferences: {
        characterId: "xiaoluo", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在这里陪你",
      } },
    });
    bridge.getLauncherAssistantApprovals.mockResolvedValue([{ requestId: "r", sessionId: "s", turnId: "t", agentId: "a",
      toolName: "command_tool", status: "pending", risk: "high", argumentSummary: {}, availableDecisions: ["accept", "decline"] }]);
    await showConversation();
    expect(container?.querySelector("header [role='status']")?.textContent).toBe("已完成");
    expect(container?.querySelector('[role="dialog"]')).toBeTruthy();
  });

  it.each(["success", "needs_continue", "error", "stopped_by_user"])("refreshes own name and appearance once after native %s turn readback", async terminalReason => {
    await renderAssistant();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "running", activeTurnId: "settings-turn", messages: [] });
    await showConversation();
    const statusReads = bridge.getLauncherAssistantStatus.mock.calls.length;
    bridge.getLauncherAssistantStatus.mockResolvedValue({ assistant: { agentId: "a", directSessionId: "s", displayName: "独立助理验收" }, settings: {
      ok: true, displayName: "独立助理验收", modelId: "m", preferences: { characterId: "xiaoluo", showStatus: false, showTitles: true, showCompletion: false, idleMessage: "休息中" },
    } });
    const terminal = { id: "s", status: "ready", lastTurnTerminalTurnId: "settings-turn", terminalReason, ledgerSeq: 10, messages: [] };
    bridge.getLauncherAssistantDetail.mockResolvedValue(terminal);
    await act(async () => { await client?.refetchQueries({ queryKey: ["launcher-assistant", "detail", "s"] }); });
    await settle();
    await settle();
    expect(conversation?.assistantDisplayName).toBe("独立助理验收");
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(statusReads + 1);

    // Detail can change while the terminal identity remains the same.
    bridge.getLauncherAssistantDetail.mockResolvedValue({ ...terminal, ledgerSeq: 11 });
    await act(async () => { await client?.refetchQueries({ queryKey: ["launcher-assistant", "detail", "s"] }); });
    await settle();
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(statusReads + 1);
    await showPet();
    expect(container?.querySelector('[role="status"]')?.hasAttribute("hidden")).toBe(true);
    expect(character).toMatchObject({ characterId: "xiaoluo", name: "独立助理验收" });
  });

  it("passes the initial operator profile only to user presentation props", async () => {
    await renderAssistant(undefined, { assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" },
      operatorProfile: { displayName: "Initial operator", avatarPreset: "codex" } });
    await showConversation();
    expect(conversation?.userDisplayName).toBe("Initial operator");
    expect(conversation?.userAvatarPreset).toBe("codex");
    expect(conversation?.assistantDisplayName).toBe("Assistant");
  });

  it.each(["success", "needs_continue", "error", "stopped_by_user"])("refreshes only operator display props once after %s without changing the assistant", async terminalReason => {
    await renderAssistant();
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "running", activeTurnId: "profile-turn", messages: [] });
    await showConversation();
    expect(conversation?.userDisplayName).toBeUndefined();
    expect(conversation?.userAvatarPreset).toBeUndefined();
    const assistantName = conversation?.assistantDisplayName;
    const statusReads = bridge.getLauncherAssistantStatus.mock.calls.length;
    bridge.getLauncherAssistantStatus.mockResolvedValue({ assistant: { agentId: "a", directSessionId: "s", displayName: assistantName },
      operatorProfile: { displayName: "Temp operator", avatarPreset: "spark" } });
    const terminal = { id: "s", status: "ready", lastTurnTerminalTurnId: "profile-turn", terminalReason, ledgerSeq: 10, messages: [] };
    bridge.getLauncherAssistantDetail.mockResolvedValue(terminal);
    await act(async () => { await client?.refetchQueries({ queryKey: ["launcher-assistant", "detail", "s"] }); });
    await settle(); await settle();
    expect(conversation?.userDisplayName).toBe("Temp operator");
    expect(conversation?.userAvatarPreset).toBe("spark");
    expect(conversation?.assistantDisplayName).toBe(assistantName);
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(statusReads + 1);
    bridge.getLauncherAssistantDetail.mockResolvedValue({ ...terminal, ledgerSeq: 11 });
    await act(async () => { await client?.refetchQueries({ queryKey: ["launcher-assistant", "detail", "s"] }); });
    await settle();
    expect(bridge.getLauncherAssistantStatus).toHaveBeenCalledTimes(statusReads + 1);
  });

  it("shows only native once-only approval actions, retains failed requests and refreshes decisions", async () => {
    const request = { requestId: "r", sessionId: "s", turnId: "t", agentId: "a", toolName: "command_tool", status: "pending", risk: "high", argumentSummary: { command: "pwd" }, availableDecisions: ["accept", "decline", "acceptAlways", "acceptWithActionWindow"] } as SessionToolApprovalRequest;
    await renderAssistant();
    bridge.getLauncherAssistantApprovals.mockResolvedValue([request]);
    bridge.resolveLauncherAssistantApproval.mockRejectedValueOnce(new Error("decision unavailable"));
    await showConversation();
    expect(container?.textContent).toContain("pwd");
    expect(container?.textContent).not.toContain("始终");
    const approve = container?.querySelector<HTMLButtonElement>('button[title="仅批准本次（Y）"]');
    expect(approve).toBeTruthy();
    await act(async () => approve?.click());
    await settle();
    expect(bridge.resolveLauncherAssistantApproval).toHaveBeenCalledWith(request, "accept");
    expect(container?.textContent).toContain("decision unavailable");
    expect(container?.querySelector('[role="dialog"]')).toBeTruthy();
    bridge.resolveLauncherAssistantApproval.mockResolvedValueOnce({ ...request, status: "declined" });
    bridge.getLauncherAssistantApprovals.mockResolvedValue([]);
    await act(async () => container?.querySelector<HTMLButtonElement>('button[title="拒绝本次（N）"]')?.click());
    await settle();
    expect(bridge.resolveLauncherAssistantApproval).toHaveBeenLastCalledWith(request, "decline");
    expect(container?.querySelector('[role="dialog"]')).toBeNull();
  });
});
