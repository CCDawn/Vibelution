// @vitest-environment happy-dom
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { act, createElement, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import type { ConversationMessage, SessionDetail, SessionReferenceAttachment, SessionToolApprovalRequest } from "../../api/types";
import type { LauncherAssistantSessionEvent } from "../../api/launcherAssistant";
import {
  launcherAssistantActivity, launcherAssistantLifecycleClosing, launcherAssistantMessageOverLimit, launcherAssistantPollInterval, launcherAssistantSendBusyCode,
  launcherAssistantSendDefinitelyRejected, launcherAssistantSendRetryableBusy, launcherAssistantSubmission,
  launcherDispatchLabel, launcherDispatchReceiptLabel, launcherAssistantQueueReadback, launcherAssistantQueueLabel, launcherAssistantRequestReadback,
  launcherAssistantSessionEventRefreshesDetail, launcherAssistantSseHealthy, launcherAssistantWaitInterval,
  launcherAssistantStatusDegradeTone,
  launcherAssistantContextRing, launcherAssistantModelDisplay, launcherAssistantEditBackfillDraft,
  LAUNCHER_ASSISTANT_MAX_MESSAGE_CHARS, LAUNCHER_ASSISTANT_SSE_HEALTH_WINDOW_MS, LAUNCHER_ASSISTANT_WAIT_POLL_FIRST_MS, LAUNCHER_ASSISTANT_WAIT_POLL_MAX_MS,
  LAUNCHER_ASSISTANT_STATUS_DEGRADE_FAILURES, LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS,
} from "./launcherAssistantModel";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";

const bridge = vi.hoisted(() => ({
  getLauncherAssistantStatus: vi.fn(), getLauncherAssistantDetail: vi.fn(), getLauncherAssistantDispatches: vi.fn(),
  hideLauncherAssistant: vi.fn(), sendLauncherAssistantMessage: vi.fn(), setLauncherAssistantExpanded: vi.fn(),
  openLauncherFromAssistant: vi.fn(), setLauncherAssistantModel: vi.fn(),
  launcherConversationApi: { cacheKey: "launcher-test" },
  getLauncherAssistantApprovals: vi.fn(), resolveLauncherAssistantApproval: vi.fn(),
  stopLauncherAssistantTurn: vi.fn(), continueLauncherAssistantTurn: vi.fn(),
  // Default: no push channel, exactly like a shell without `onSessionEvent`.
  subscribeLauncherAssistantSessionEvent: vi.fn((): (() => void) | null => null),
}));
vi.mock("../../api/launcherAssistant", async importOriginal => ({ ...await importOriginal<typeof import("../../api/launcherAssistant")>(), ...bridge }));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
let character: { characterId: string; name: string } | undefined;
vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: (props: typeof character) => { character = props; return null; } }));
let conversation: ConversationViewProps | undefined;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => { conversation = props; return createElement("div", { "data-testid": "assistant-conversation" }, props.composerPrecedingContent, props.composerModelControl); },
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
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith("vibelution.launcher-assistant.composer.")) localStorage.removeItem(key);
  }
  conversation = undefined;
  vi.clearAllMocks();
  // clearAllMocks keeps implementations; put the push channel back to "absent".
  bridge.subscribeLauncherAssistantSessionEvent.mockImplementation(() => null);
});

async function renderAssistant(initialDetail?: Record<string, unknown>, initialStatus?: Record<string, unknown>, statusRequest?: () => Promise<unknown>, routeProps: Partial<ComponentProps<typeof LauncherAssistantRoute>> = {}, detailRequest?: () => Promise<unknown>) {
  if (statusRequest) bridge.getLauncherAssistantStatus.mockImplementation(statusRequest);
  else bridge.getLauncherAssistantStatus.mockResolvedValue(initialStatus ?? { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" } });
  if (detailRequest) bridge.getLauncherAssistantDetail.mockImplementation(detailRequest);
  else bridge.getLauncherAssistantDetail.mockResolvedValue(initialDetail ?? { id: "s", status: "ready", messages: [], defaultFileContext: "" });
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
    root?.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantRoute, { key: "pet", ...routeProps })));
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(10);
    else await new Promise(resolve => setTimeout(resolve, 10));
  });
  await settle();
}
async function settle() {
  await act(async () => {
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(10);
    else await new Promise(resolve => setTimeout(resolve, 10));
  });
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
  it("restores a draft after a fresh renderer without sending it", async () => {
    await renderAssistant(undefined, undefined, undefined, { embedded: true });
    await act(async () => conversation?.onComposerChange("重开后保留的草稿"));
    await act(async () => root?.unmount());
    container?.remove();
    client?.clear();
    await renderAssistant(undefined, undefined, undefined, { embedded: true });
    expect(conversation?.composerValue).toBe("重开后保留的草稿");
    expect(bridge.sendLauncherAssistantMessage).not.toHaveBeenCalled();
  });
  it("restores an unconfirmed request after a fresh renderer and retries only its original ID", async () => {
    bridge.sendLauncherAssistantMessage.mockRejectedValueOnce(new Error("ASSISTANT_LIFECYCLE_CLOSING"));
    await renderAssistant(undefined, undefined, undefined, { embedded: true });
    await act(async () => conversation?.onComposerChange("请求 A"));
    await act(async () => conversation?.onSubmit());
    const original = bridge.sendLauncherAssistantMessage.mock.calls[0];
    await act(async () => conversation?.onComposerChange("新的草稿 B"));
    await act(async () => root?.unmount());
    container?.remove();
    client?.clear();
    await renderAssistant(undefined, undefined, undefined, { embedded: true });
    expect(conversation?.composerValue).toBe("新的草稿 B");
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
    bridge.sendLauncherAssistantMessage.mockResolvedValueOnce({ turnId: "restored-request" });
    await act(async () => conversation?.onSubmit());
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(2);
    expect(bridge.sendLauncherAssistantMessage.mock.calls[1]).toEqual(original);
    expect(conversation?.composerValue).toBe("新的草稿 B");
  });
  it("sends an explicit contextual request without consuming the user's draft", async () => {
    const entryIntent = { key: "affairs", title: "在对话里管理待办与提醒", label: "查看我的待办与提醒", message: "请查看我的待办与提醒，先不要修改。" };
    bridge.sendLauncherAssistantMessage.mockResolvedValue({ turnId: "accepted-context" });
    await renderAssistant(undefined, undefined, undefined, { embedded: true, entryIntent });
    expect(bridge.sendLauncherAssistantMessage).not.toHaveBeenCalled();
    await act(async () => conversation?.onComposerChange?.("还没发送的草稿"));
    await click(entryIntent.label);
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(1);
    expect(bridge.sendLauncherAssistantMessage.mock.calls[0][0]).toBe(entryIntent.message);
    expect(conversation?.composerValue).toBe("还没发送的草稿");
  });
  it("retries the original contextual UUID after a lost ACK and keeps the draft", async () => {
    const entryIntent = { key: "preferences", title: "调整回答方式", label: "查看偏好", message: "请读取当前对话偏好。" };
    bridge.sendLauncherAssistantMessage.mockRejectedValueOnce(new Error("lost ACK")).mockResolvedValue({ turnId: "accepted-context" });
    await renderAssistant(undefined, undefined, undefined, { embedded: true, entryIntent });
    await act(async () => conversation?.onComposerChange?.("保留这段草稿"));
    await click(entryIntent.label);
    const originalId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    await act(async () => { await conversation?.onSubmit?.(); });
    expect(bridge.sendLauncherAssistantMessage).toHaveBeenCalledTimes(2);
    expect(bridge.sendLauncherAssistantMessage.mock.calls[1]).toEqual(bridge.sendLauncherAssistantMessage.mock.calls[0]);
    expect(originalId).toMatch(/^[0-9a-f-]{36}$/);
    expect(conversation?.composerValue).toBe("保留这段草稿");
  });
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

  it("keeps reading an unconfirmed send back while hidden and stops once the evidence lands", async () => {
    vi.useFakeTimers();
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      // An unknown send outcome keeps the conservative unconfirmed lock and the
      // original request; nothing here is a provable pre-admission refusal.
      bridge.sendLauncherAssistantMessage.mockRejectedValueOnce(new Error("ASSISTANT_HTTP_FAILED"));
      await renderAssistant();
      await showConversation();
      await act(async () => conversation?.onComposerChange("请求 A"));
      await act(async () => conversation?.onSubmit());
      const requestId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
      expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ outstanding: { requestId } });
      expect(conversation?.composerDisabled).toBe(true);
      await act(async () => {
        visibility.mockReturnValue("hidden");
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await settle();
      // Past one fallback window the hidden window has kept reading for the send.
      const reads = bridge.getLauncherAssistantDetail.mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(10_500); });
      await settle();
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 1);
      // The readback evidence lands through that hidden poll and heals the send.
      bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "healed", terminalReason: "success",
        messages: [{ role: "user", metadata: { clientSubmissionId: requestId, turnId: "healed" } }] });
      await act(async () => { await vi.advanceTimersByTimeAsync(10_500); });
      await settle();
      // The outstanding lock clears; the accepted turn ID is consumed at once
      // by the route's authoritative-confirmation effect ("healed" appears in
      // the terminal snapshot), so it reads back empty rather than pending.
      expect(client?.getQueryData(["launcher-assistant", "composer", "s"])).toMatchObject({ outstanding: null, acceptedTurnId: "" });
      expect(conversation?.composerDisabled).toBe(false);
      // Hidden again with nothing outstanding: the polling is off once more.
      const healed = bridge.getLauncherAssistantDetail.mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(21_000); });
      await settle();
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(healed);
    } finally {
      visibility.mockRestore();
      vi.useRealTimers();
    }
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
    // Hidden keeps only the outstanding-request readback alive, pinned to the fallback cadence.
    expect(launcherAssistantPollInterval(false, unrelated, "", null, ["original"])).toBe(10_000);
    const terminal = { ...unrelated, lastTurnTerminalTurnId: "matching", messages: [{ role: "user", metadata: { clientSubmissionId: "original", turnId: "matching" } }] } as unknown as SessionDetail;
    expect(launcherAssistantRequestReadback(terminal, "original")).toEqual({ turnId: "matching", queuedAcceptance: null });
    expect(launcherAssistantPollInterval(true, terminal, "", null, ["original"])).toBe(false);
    // Authoritative evidence for the pending request stops the hidden readback too.
    expect(launcherAssistantPollInterval(false, terminal, "", null, ["original"])).toBe(false);
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
    const reference = { kind: "message", referenceId: "message:m1", sourceMessageId: "m1", quote: "text" } as SessionReferenceAttachment;
    expect(launcherAssistantSubmission(null, " see this ", createId, [], [], [reference]))
      .toEqual({ message: "see this", requestId: "id-1", draftSnapshot: " see this ", references: [reference] });
    expect(launcherAssistantSubmission(null, "   ", createId, [], [], [reference]))
      .toEqual({ message: "", requestId: "id-1", draftSnapshot: "   ", references: [reference] });
  });

  it("pre-checks the host message length bound without changing the retry contract", () => {
    expect(LAUNCHER_ASSISTANT_MAX_MESSAGE_CHARS).toBe(64_000);
    expect(launcherAssistantMessageOverLimit("x".repeat(64_000))).toBe(false);
    expect(launcherAssistantMessageOverLimit("x".repeat(64_001))).toBe(true);
  });

  it("unlocks only on provable pre-admission refusals, never on unknown outcomes", () => {
    const rejected = Object.assign(new Error("消息或请求标识无效。"), { name: "LauncherAssistantRejectedError" });
    const bridgeRefused = new Error("ASSISTANT_REQUEST_INVALID");
    const unknown = [new Error("ASSISTANT_HTTP_FAILED"), new Error("ASSISTANT_NOT_READY"),
      new Error("Launcher 尚未确认消息所属轮次。"), new Error("network down"), "string failure", undefined];
    expect(launcherAssistantSendDefinitelyRejected(rejected)).toBe(true);
    expect(launcherAssistantSendDefinitelyRejected(bridgeRefused)).toBe(true);
    expect(launcherAssistantSendDefinitelyRejected(new Error("Error invoking remote method 'assistant:request': Error: ASSISTANT_REQUEST_INVALID"))).toBe(true);
    for (const error of unknown) expect(launcherAssistantSendDefinitelyRejected(error)).toBe(false);
    // An HTTP failure is neither a provable refusal nor retryable-busy: its
    // outcome is unknown, so the conservative unconfirmed lock stays.
    expect(launcherAssistantSendRetryableBusy(new Error("ASSISTANT_HTTP_FAILED"))).toBe(false);
  });

  it.each([
    ["ASSISTANT_QUIESCING", new Error("ASSISTANT_QUIESCING")],
    ["ASSISTANT_QUIESCING (ipc wrap)", new Error("Error invoking remote method 'launcherAssistant:invoke': Error: ASSISTANT_QUIESCING")],
    ["ASSISTANT_QUIESCENCE_BUSY", new Error("ASSISTANT_QUIESCENCE_BUSY")],
    ["ASSISTANT_QUIESCENCE_BUSY (ipc wrap)", new Error("Error invoking remote method 'launcherAssistant:invoke': ASSISTANT_QUIESCENCE_BUSY")],
    ["ASSISTANT_STOPPING (name)", Object.assign(new Error("host is stopping"), { name: "ASSISTANT_STOPPING" })],
    ["ASSISTANT_NOT_READY", new Error("ASSISTANT_NOT_READY")],
    ["ASSISTANT_NOT_READY (ipc wrap)", new Error("Error invoking remote method 'assistant:request': Error: ASSISTANT_NOT_READY")],
    ["ASSISTANT_SESSION_CONFLICT", new Error("ASSISTANT_SESSION_CONFLICT")],
  ] as const)("classifies %s as retryable busy and reports its code", (_label, error) => {
    expect(launcherAssistantSendRetryableBusy(error)).toBe(true);
    // Never a provable rejection: these codes retry the retained request.
    expect(launcherAssistantSendDefinitelyRejected(error)).toBe(false);
    expect(launcherAssistantSendBusyCode(error)).toBe(_label.split(" ")[0]);
  });

  it.each([
    ["timeout", new Error("host request timed out after 5000ms")],
    ["transport failure", new Error("TRANSPORT_FAILED")],
    ["http failure", new Error("ASSISTANT_HTTP_FAILED")],
    ["model busy keeps its api-layer path", new Error("ASSISTANT_MODEL_BUSY")],
    ["definite rejection keeps its own unlock", new Error("ASSISTANT_REQUEST_INVALID")],
    ["prefix must not match (ASSISTANT_NOT_YET_READY)", new Error("ASSISTANT_NOT_YET_READY")],
    ["substring must not match", new Error("retry after ASSISTANT_STOPPING completed")],
    ["non-error value", "ASSISTANT_QUIESCING"],
  ] as const)("does not classify %s as retryable busy", (_label, error) => {
    expect(launcherAssistantSendRetryableBusy(error)).toBe(false);
    expect(launcherAssistantSendBusyCode(error)).toBe("");
  });

  it.each([
    ["bare code", new Error("ASSISTANT_LIFECYCLE_CLOSING")],
    ["ipc wrap", new Error("Error invoking remote method 'assistant:invoke': Error: ASSISTANT_LIFECYCLE_CLOSING")],
    ["ipc wrap without second Error", new Error("Error invoking remote method 'assistant:invoke': ASSISTANT_LIFECYCLE_CLOSING")],
  ] as const)("classifies a %s as a lifecycle-closing refusal", (_label, error) => {
    expect(launcherAssistantLifecycleClosing(error)).toBe(true);
    // The closing refusal is neither a pre-admission send rejection nor a
    // retryable-busy quiescence: it names the resident host's own retirement.
    expect(launcherAssistantSendDefinitelyRejected(error)).toBe(false);
    expect(launcherAssistantSendRetryableBusy(error)).toBe(false);
  });

  it.each([
    ["cold-boot transport failure", new Error("backend unreachable")],
    ["not-ready cold start", new Error("ASSISTANT_NOT_READY")],
    ["prefix must not match", new Error("ASSISTANT_LIFECYCLE_CLOSING_SOON")],
    ["substring must not match", new Error("retry after ASSISTANT_LIFECYCLE_CLOSING completed")],
    ["non-error value", "ASSISTANT_LIFECYCLE_CLOSING"],
    ["undefined", undefined],
  ] as const)("keeps %s out of the lifecycle-closing classification", (_label, error) => {
    expect(launcherAssistantLifecycleClosing(error)).toBe(false);
  });

  it("polls only a visible initial or active native session", () => {
    expect(launcherAssistantPollInterval(false, { status: "running" })).toBe(false);
    expect(launcherAssistantPollInterval(true)).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "running" })).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "queued" })).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "ready" })).toBe(false);
  });

  it("keeps every active branch at 2s without a push channel and backs off to 10s only while it is healthy", () => {
    const quiet = { sseHealthy: false };
    const healthy = { sseHealthy: true };
    const unrecovered = { status: "ready", messages: [] } as unknown as SessionDetail;
    const receipt = { id: "q", clientSubmissionId: "r", observed: false };
    // Regression: an explicit false (and an empty options bag) match today's values branch by branch.
    expect(launcherAssistantPollInterval(true, undefined, "", null, [], {})).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "running" }, "", null, [], quiet)).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "ready", lastTurnTerminalTurnId: "old" }, "new", null, [], quiet)).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "ready" }, "", receipt, [], quiet)).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "ready", queuedTurns: [{ id: "q", status: "queued" }] }, "", null, [], quiet)).toBe(2_000);
    expect(launcherAssistantPollInterval(true, unrecovered, "", null, ["missing"], quiet)).toBe(2_000);
    expect(launcherAssistantPollInterval(true, { status: "ready" }, "", null, [], quiet)).toBe(false);
    expect(launcherAssistantPollInterval(false, { status: "running" }, "", null, [], quiet)).toBe(false);
    // Healthy push channel: each former 2s branch becomes the 10s safety net.
    expect(launcherAssistantPollInterval(true, undefined, "", null, [], healthy)).toBe(10_000);
    expect(launcherAssistantPollInterval(true, { status: "running" }, "", null, [], healthy)).toBe(10_000);
    expect(launcherAssistantPollInterval(true, { status: "queued" }, "", null, [], healthy)).toBe(10_000);
    expect(launcherAssistantPollInterval(true, { status: "ready", lastTurnTerminalTurnId: "old" }, "new", null, [], healthy)).toBe(10_000);
    expect(launcherAssistantPollInterval(true, { status: "ready" }, "", receipt, [], healthy)).toBe(10_000);
    expect(launcherAssistantPollInterval(true, { status: "ready", queuedTurns: [{ id: "q", status: "starting" }] }, "", null, [], healthy)).toBe(10_000);
    expect(launcherAssistantPollInterval(true, unrecovered, "", null, ["missing"], healthy)).toBe(10_000);
    // Idle and settled branches stay off no matter how healthy the channel is,
    // and a hidden window without outstanding requests stays off too.
    expect(launcherAssistantPollInterval(true, { status: "ready" }, "", null, [], healthy)).toBe(false);
    expect(launcherAssistantPollInterval(true, { status: "ready", lastTurnTerminalTurnId: "new", terminalReason: "success" }, "new", null, [], healthy)).toBe(false);
    expect(launcherAssistantPollInterval(false, { status: "running" }, "", null, [], healthy)).toBe(false);
    // Hidden with an outstanding request keeps exactly one lifeline alive: the
    // readback, at the fixed fallback cadence whether the stale flag still says
    // healthy or has already decayed (the push subscription died with the window).
    expect(launcherAssistantPollInterval(false, undefined, "", null, ["missing"], healthy)).toBe(10_000);
    expect(launcherAssistantPollInterval(false, undefined, "", null, ["missing"])).toBe(10_000);
  });

  it("calls the push channel healthy only for an event inside the 35s window", () => {
    const now = 1_000_000;
    expect(LAUNCHER_ASSISTANT_SSE_HEALTH_WINDOW_MS).toBe(35_000);
    expect(launcherAssistantSseHealthy(null, now)).toBe(false);
    expect(launcherAssistantSseHealthy(undefined, now)).toBe(false);
    expect(launcherAssistantSseHealthy(Number.NaN, now)).toBe(false);
    expect(launcherAssistantSseHealthy(now, now)).toBe(true);
    expect(launcherAssistantSseHealthy(now + 5, now)).toBe(true);
    expect(launcherAssistantSseHealthy(now - LAUNCHER_ASSISTANT_SSE_HEALTH_WINDOW_MS, now)).toBe(true);
    expect(launcherAssistantSseHealthy(now - LAUNCHER_ASSISTANT_SSE_HEALTH_WINDOW_MS - 1, now)).toBe(false);
  });

  it("debounces the status degrade: one failed poll is a hint, persistent failure over a dead channel is red", () => {
    const mounted = { isError: true, isFetching: false, hasData: true, consecutiveFailures: 0, lastSuccessAt: 1_000, now: 1_000, sseHealthy: false };
    expect(LAUNCHER_ASSISTANT_STATUS_DEGRADE_FAILURES).toBe(2);
    expect(LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS).toBe(30_000);
    // The never-succeeded cold boot is owned by the backend-wait surface.
    expect(launcherAssistantStatusDegradeTone({ ...mounted, hasData: false, consecutiveFailures: 5 })).toBe("quiet");
    // A paused poller (no error, no attempt in flight) is not failure evidence,
    // even when the last success is far back.
    expect(launcherAssistantStatusDegradeTone({ ...mounted, isError: false, now: 1_000 + 10 * 60_000 })).toBe("quiet");
    // A single failed poll stays at the weak hint.
    expect(launcherAssistantStatusDegradeTone({ ...mounted, consecutiveFailures: 1 })).toBe("soft");
    // Two consecutive failed polls over a dead push channel escalate…
    expect(launcherAssistantStatusDegradeTone({ ...mounted, consecutiveFailures: 2 })).toBe("error");
    // …and the 30s silence gap escalates strictly past its boundary.
    expect(launcherAssistantStatusDegradeTone({ ...mounted, consecutiveFailures: 1,
      now: 1_000 + LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS })).toBe("soft");
    expect(launcherAssistantStatusDegradeTone({ ...mounted, consecutiveFailures: 1,
      now: 1_000 + LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS + 1 })).toBe("error");
  });

  it("caps the status degrade at the weak hint while the push channel is alive", () => {
    const mounted = { isError: true, isFetching: false, hasData: true, consecutiveFailures: 6, lastSuccessAt: 1_000, now: 1_000, sseHealthy: true };
    expect(launcherAssistantStatusDegradeTone(mounted)).toBe("soft");
    expect(launcherAssistantStatusDegradeTone({ ...mounted, now: 1_000 + LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS + 1 })).toBe("soft");
  });

  it("treats a hung in-flight status read past the silence gap as degraded, not a paused poller", () => {
    const mounted = { isError: false, isFetching: true, hasData: true, consecutiveFailures: 0, lastSuccessAt: 1_000, now: 1_000, sseHealthy: false };
    expect(launcherAssistantStatusDegradeTone(mounted)).toBe("quiet");
    expect(launcherAssistantStatusDegradeTone({ ...mounted, now: 1_000 + LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS })).toBe("quiet");
    expect(launcherAssistantStatusDegradeTone({ ...mounted, now: 1_000 + LAUNCHER_ASSISTANT_STATUS_DEGRADE_MAX_SILENCE_MS + 1 })).toBe("error");
  });

  it("backs the cold-boot backend wait off from 2s to a 16s cap", () => {
    const start = 1_000_000;
    expect(LAUNCHER_ASSISTANT_WAIT_POLL_FIRST_MS).toBe(2_000);
    expect(LAUNCHER_ASSISTANT_WAIT_POLL_MAX_MS).toBe(16_000);
    // Before the first failure is stamped, and inside the first 4s window, probe every 2s.
    expect(launcherAssistantWaitInterval(null, start)).toBe(2_000);
    expect(launcherAssistantWaitInterval(start, start)).toBe(2_000);
    expect(launcherAssistantWaitInterval(start, start + 1_999)).toBe(2_000);
    expect(launcherAssistantWaitInterval(start, start - 5)).toBe(2_000);
    // One doubling per elapsed 4s window.
    expect(launcherAssistantWaitInterval(start, start + 4_000)).toBe(4_000);
    expect(launcherAssistantWaitInterval(start, start + 8_000)).toBe(8_000);
    expect(launcherAssistantWaitInterval(start, start + 16_000)).toBe(16_000);
    // A long outage never grows past the cap.
    expect(launcherAssistantWaitInterval(start, start + 10 * 60_000)).toBe(16_000);
    // Non-finite clocks degrade to the first window instead of throwing.
    expect(launcherAssistantWaitInterval(Number.NaN, start)).toBe(2_000);
    expect(launcherAssistantWaitInterval(start, Number.NaN)).toBe(2_000);
  });

  it("re-reads detail only for this session's snapshot frame or an explicitly finished delta", () => {
    const at = 1;
    const frame = (patch: Record<string, unknown>) => ({ type: "assistant_delta", sessionId: "s", at, ...patch }) as LauncherAssistantSessionEvent;
    expect(launcherAssistantSessionEventRefreshesDetail({ type: "session_detail", sessionId: "s", at }, "s")).toBe(true);
    expect(launcherAssistantSessionEventRefreshesDetail({ type: "session_detail", sessionId: "other", at }, "s")).toBe(false);
    expect(launcherAssistantSessionEventRefreshesDetail({ type: "session_detail", sessionId: "s", at }, "")).toBe(false);
    expect(launcherAssistantSessionEventRefreshesDetail({ type: "heartbeat", sessionId: "s", at }, "s")).toBe(false);
    expect(launcherAssistantSessionEventRefreshesDetail({ type: "unknown_frame", sessionId: "s", at }, "s")).toBe(false);
    // `done` is outside the frozen envelope: absent, falsy or non-boolean never counts as finished.
    expect(launcherAssistantSessionEventRefreshesDetail(frame({}), "s")).toBe(false);
    expect(launcherAssistantSessionEventRefreshesDetail(frame({ done: false }), "s")).toBe(false);
    expect(launcherAssistantSessionEventRefreshesDetail(frame({ done: "true" }), "s")).toBe(false);
    expect(launcherAssistantSessionEventRefreshesDetail(frame({ done: true }), "s")).toBe(true);
    expect(launcherAssistantSessionEventRefreshesDetail(frame({ done: true, sessionId: "other" }), "s")).toBe(false);
  });

  it("re-reads detail from a pushed authoritative frame, leaves other frames read-only and unsubscribes on unmount", async () => {
    let push: ((event: LauncherAssistantSessionEvent) => void) | undefined;
    const unsubscribe = vi.fn();
    bridge.subscribeLauncherAssistantSessionEvent.mockImplementation((listener: (event: LauncherAssistantSessionEvent) => void) => { push = listener; return unsubscribe; });
    await renderAssistant();
    expect(bridge.subscribeLauncherAssistantSessionEvent).toHaveBeenCalledTimes(1);
    expect(push).toBeTypeOf("function");
    const reads = bridge.getLauncherAssistantDetail.mock.calls.length;
    const deliver = async (event: LauncherAssistantSessionEvent) => {
      await act(async () => { push?.(event); });
      await settle(); await settle();
    };
    await deliver({ type: "heartbeat", sessionId: "s", at: Date.now() });
    await deliver({ type: "session_detail", sessionId: "other", at: Date.now() });
    await deliver({ type: "assistant_delta", sessionId: "s", at: Date.now() });
    await deliver({ type: "unknown_frame", sessionId: "s", at: Date.now() });
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 1);
    await deliver({ type: "session_detail", sessionId: "s", ledgerSeq: 3, at: Date.now() });
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 2);
    await deliver({ type: "assistant_delta", sessionId: "s", at: Date.now(), done: true } as LauncherAssistantSessionEvent);
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 3);
    expect(unsubscribe).not.toHaveBeenCalled();
    await act(async () => root?.unmount());
    root = undefined;
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it("keeps one pending detail recovery read through repeated push gaps and allows a later recovery read", async () => {
    let push: ((event: LauncherAssistantSessionEvent) => void) | undefined;
    bridge.subscribeLauncherAssistantSessionEvent.mockImplementation((listener: (event: LauncherAssistantSessionEvent) => void) => {
      push = listener;
      return () => {};
    });
    const initialDetail = { id: "s", status: "running", activeTurnId: "t1", messages: [], defaultFileContext: "", ledgerSeq: 1 };
    await renderAssistant(initialDetail, undefined, undefined, { embedded: true });
    expect(push).toBeTypeOf("function");
    expect(client?.getQueryData(["launcher-assistant", "detail", "s"])).toMatchObject(initialDetail);
    const reads = bridge.getLauncherAssistantDetail.mock.calls.length;
    let resolveDetail!: (detail: typeof initialDetail) => void;
    const pendingDetail = new Promise<typeof initialDetail>(resolve => { resolveDetail = resolve; });
    bridge.getLauncherAssistantDetail.mockImplementation(() => pendingDetail);
    const freshDetail = { ...initialDetail, ledgerSeq: 5 };
    const deliverGap = async (ledgerSeq: number) => {
      await act(async () => {
        push?.({ type: "assistant_delta", sessionId: "s", turnId: "t1", needsRefresh: true, ledgerSeq, at: Date.now() });
      });
      await settle();
    };

    try {
      await deliverGap(2);
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 1);
      for (const ledgerSeq of [3, 4, 5]) await deliverGap(ledgerSeq);
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 1);

      await act(async () => resolveDetail(freshDetail));
      await settle(); await settle();
      expect(client?.getQueryData(["launcher-assistant", "detail", "s"])).toMatchObject(freshDetail);

      const laterDetail = { ...initialDetail, ledgerSeq: 6 };
      bridge.getLauncherAssistantDetail.mockResolvedValue(laterDetail);
      await deliverGap(6);
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 2);
      expect(client?.getQueryData(["launcher-assistant", "detail", "s"])).toMatchObject(laterDetail);
    } finally {
      await act(async () => resolveDetail(freshDetail));
      await settle();
    }
  });

  it("replaces a pending old-epoch detail read and waits for the new epoch before accepting appends", async () => {
    let push: ((event: LauncherAssistantSessionEvent) => void) | undefined;
    bridge.subscribeLauncherAssistantSessionEvent.mockImplementation((listener: (event: LauncherAssistantSessionEvent) => void) => {
      push = listener;
      return () => {};
    });
    const item = { id: "native-answer", itemId: "native-answer", version: 3, sessionId: "s", turnId: "t1", revision: 1,
      sequence: 1, status: "running", type: "agent_message", phase: "final_answer", text: "seed" };
    const detailWithText = (text: string) => ({ id: "s", status: "running", activeTurnId: "t1", currentPhase: "responding",
      messages: [{ id: "m1", role: "assistant", turnId: "t1", status: "running", turnItems: [{ ...item, text }] }],
      defaultFileContext: "", ledgerSeq: 10 });
    const initialDetail = { ...detailWithText("seed"), messages: [] };
    await renderAssistant(initialDetail, undefined, undefined, { embedded: true });
    const frame = { type: "assistant_delta", sessionId: "s", turnId: "t1", at: 1, ledgerSeq: 10,
      updatedAt: "2026-11-03T02:00:00Z", stage: "assistant_response", done: false };
    await act(async () => push?.({ ...frame, deltaSeq: 1, turnItems: [item] } as LauncherAssistantSessionEvent));
    expect(conversation?.activeTurnMessage?.turnItems?.[0]).toMatchObject({ text: "seed" });

    const reads = bridge.getLauncherAssistantDetail.mock.calls.length;
    let resolveOld!: (detail: ReturnType<typeof detailWithText>) => void;
    let resolveNew!: (detail: ReturnType<typeof detailWithText>) => void;
    const oldRead = new Promise<ReturnType<typeof detailWithText>>(resolve => { resolveOld = resolve; });
    const newRead = new Promise<ReturnType<typeof detailWithText>>(resolve => { resolveNew = resolve; });
    bridge.getLauncherAssistantDetail.mockImplementationOnce(() => oldRead).mockImplementation(() => newRead);
    const deliver = async (event: LauncherAssistantSessionEvent) => {
      await act(async () => push?.(event));
      await settle();
    };
    const newDetail = detailWithText("🐳abc");

    try {
      await deliver({ type: "heartbeat", sessionId: "s", connectionEpoch: 1, ledgerSeq: 10, at: 2 });
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 1);
      await deliver({ type: "heartbeat", sessionId: "s", connectionEpoch: 2, ledgerSeq: 10, at: 3 });
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(reads + 2);

      // Equal journal watermark and text length cannot make the old read fresh
      // for the new connection; its different body must remain unobservable.
      await act(async () => resolveOld(detailWithText("old!")));
      await settle(); await settle();
      expect(client?.getQueryData(["launcher-assistant", "detail", "s"])).toMatchObject(initialDetail);
      expect(conversation?.activeTurnMessage?.turnItems?.[0]).toMatchObject({ text: "seed" });
      const append = { ...frame, connectionEpoch: 2, deltaSeq: 1, deltaSeqFrom: 1, turnItems: [], streamEncoding: "append-v1",
        turnItemAppends: [{ kind: "append", itemId: "native-answer", itemType: "agent_message", baseLength: 4, appendedLength: 1, appendedText: "?" }] };
      await deliver(append as LauncherAssistantSessionEvent);
      expect(conversation?.activeTurnMessage?.turnItems?.[0]).toMatchObject({ text: "seed" });

      await act(async () => resolveNew(newDetail));
      await settle(); await settle();
      expect(client?.getQueryData(["launcher-assistant", "detail", "s"])).toMatchObject(newDetail);
      await deliver({ ...append, deltaSeq: 2, deltaSeqFrom: 2,
        turnItemAppends: [{ ...append.turnItemAppends[0], appendedLength: 2, appendedText: "继续" }] } as LauncherAssistantSessionEvent);
      expect(conversation?.activeTurnMessage?.turnItems?.[0]).toMatchObject({ text: "🐳abc继续" });

      const settledReads = bridge.getLauncherAssistantDetail.mock.calls.length;
      await deliver({ ...frame, connectionEpoch: 1, deltaSeq: 100, deltaSeqFrom: 100, done: true,
        turnItems: [{ ...item, text: "old!", status: "completed", terminal: true }] } as LauncherAssistantSessionEvent);
      expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(settledReads);
      expect(conversation?.activeTurnMessage?.turnItems?.[0]).toMatchObject({ text: "🐳abc继续" });
    } finally {
      await act(async () => { resolveOld(detailWithText("old!")); resolveNew(newDetail); });
      await settle();
    }
  });

  it("replaces an initial detail read without cached data when the connection epoch changes", async () => {
    let push: ((event: LauncherAssistantSessionEvent) => void) | undefined;
    bridge.subscribeLauncherAssistantSessionEvent.mockImplementation(listener => { push = listener; return () => {}; });
    const snapshot = (ledgerSeq: number) => ({ id: "s", status: "ready", messages: [], defaultFileContext: "", ledgerSeq });
    let resolveInitial!: (value: ReturnType<typeof snapshot>) => void;
    const initial = new Promise<ReturnType<typeof snapshot>>(resolve => { resolveInitial = resolve; });
    let requests = 0;
    await renderAssistant(undefined, undefined, undefined, { embedded: true }, () => {
      requests++;
      return requests === 1 ? initial : Promise.resolve(snapshot(20));
    });
    try {
      expect(client?.getQueryData(["launcher-assistant", "detail", "s"])).toBeUndefined();
      await act(async () => push?.({ type: "heartbeat", sessionId: "s", at: 1, connectionEpoch: 1 }));
      await settle(); await settle();
      expect(requests).toBe(2);
      expect(client?.getQueryData(["launcher-assistant", "detail", "s"])).toMatchObject(snapshot(20));
      await act(async () => resolveInitial(snapshot(10)));
      await settle();
      expect(client?.getQueryData(["launcher-assistant", "detail", "s"])).toMatchObject(snapshot(20));
    } finally {
      resolveInitial(snapshot(10));
      await settle();
    }
  });

  it("applies native full and append frames with one stable item identity until durable readback", async () => {
    let push: ((event: LauncherAssistantSessionEvent) => void) | undefined;
    bridge.subscribeLauncherAssistantSessionEvent.mockImplementation((listener: (event: LauncherAssistantSessionEvent) => void) => { push = listener; return () => {}; });
    await renderAssistant({ id: "s", status: "running", activeTurnId: "t1", messages: [], defaultFileContext: "", ledgerSeq: 0 }, undefined, undefined, { embedded: true });
    const item = { id: "native-answer", itemId: "native-answer", version: 3, sessionId: "s", turnId: "t1", revision: 1, sequence: 1, status: "running", type: "agent_message", phase: "final_answer", text: "第一段" };
    const frame = { type: "assistant_delta", sessionId: "s", turnId: "t1", at: 1, updatedAt: "2026-11-03T02:00:00Z", stage: "assistant_response", done: false };
    await act(async () => push?.({ ...frame, deltaSeq: 1, ledgerSeq: 1, turnItems: [item] } as LauncherAssistantSessionEvent));
    expect(conversation?.activeTurnMessage?.turnItems?.[0]).toMatchObject({ itemId: "native-answer", text: "第一段" });
    await act(async () => push?.({ ...frame, deltaSeq: 2, ledgerSeq: 2, turnItems: [], streamEncoding: "append-v1", turnItemAppends: [{ kind: "append", itemId: "native-answer", itemType: "agent_message", baseLength: 3, appendedLength: 3, appendedText: "第二段" }] } as LauncherAssistantSessionEvent));
    expect(conversation?.activeTurnMessage?.turnItems).toHaveLength(1);
    expect(conversation?.activeTurnMessage?.turnItems?.[0]).toMatchObject({ itemId: "native-answer", text: "第一段第二段" });
    const completed = { ...item, text: "第一段第二段", status: "completed", terminal: true };
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", currentPhase: "ready", activeTurnId: "", ledgerSeq: 3, defaultFileContext: "", messages: [{ id: "m1", role: "assistant", turnId: "t1", status: "completed", turnItems: [completed] }] });
    await act(async () => push?.({ ...frame, deltaSeq: 3, ledgerSeq: 3, done: true, turnItems: [completed] } as LauncherAssistantSessionEvent));
    await settle(); await settle();
    expect(conversation?.activeTurnMessage).toBeUndefined();
    expect(conversation?.messages[0].turnItems?.[0]).toMatchObject({ text: "第一段第二段" });
  });

  it("keeps the conversation mounted through a visibility restore and refreshes detail in place", async () => {
    await renderAssistant({ id: "s", status: "ready", messages: [], defaultFileContext: "" }, undefined, undefined, { embedded: true });
    expect(container?.querySelector("[data-testid=assistant-conversation]")).toBeTruthy();
    const reads = bridge.getLauncherAssistantDetail.mock.calls.length;
    const original = Object.getOwnPropertyDescriptor(document, "visibilityState");
    const setVisibility = (value: string) => Object.defineProperty(document, "visibilityState", { configurable: true, value });
    try {
      setVisibility("hidden");
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
      setVisibility("visible");
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
      // The restore must repaint from the cached conversation synchronously:
      // an epoch-keyed detail query would drop the cache for a frame and
      // unmount the chat view right here.
      expect(container?.querySelector("[data-testid=assistant-conversation]")).toBeTruthy();
      await settle(); await settle(); await settle();
      expect(bridge.getLauncherAssistantDetail.mock.calls.length).toBeGreaterThan(reads);
    } finally {
      if (original) Object.defineProperty(document, "visibilityState", original);
      else delete (document as { visibilityState?: unknown }).visibilityState;
    }
  });

  it("backs an active session's polling off to the 10s safety net once the push channel proves healthy", async () => {
    let push: ((event: LauncherAssistantSessionEvent) => void) | undefined;
    bridge.subscribeLauncherAssistantSessionEvent.mockImplementation((listener: (event: LauncherAssistantSessionEvent) => void) => { push = listener; return () => {}; });
    await renderAssistant({ id: "s", status: "running", activeTurnId: "t", messages: [], defaultFileContext: "" });
    // No frame has arrived: the active session keeps today's 2s cadence.
    const silent = bridge.getLauncherAssistantDetail.mock.calls.length;
    await pollCycle();
    expect(bridge.getLauncherAssistantDetail.mock.calls.length).toBeGreaterThan(silent);
    // An authoritative frame re-reads detail at once; with the channel now
    // healthy the following 2s window passes without a single poll.
    const before = bridge.getLauncherAssistantDetail.mock.calls.length;
    await act(async () => { push?.({ type: "session_detail", sessionId: "s", at: Date.now() }); });
    await settle(); await settle();
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(before + 1);
    await pollCycle();
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledTimes(before + 1);
  }, 10_000);

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

  it("reads a known failure code as its short label and keeps the generic fallback for unknown codes", () => {
    expect(launcherDispatchLabel({ dispatchId: "d", lastError: { code: "TASK_NOT_FOUND" } }, "zh")).toBe("任务不存在");
    expect(launcherDispatchLabel({ dispatchId: "d", lastError: { code: "BACKEND_TIMEOUT" } }, "en")).toBe("Backend timeout");
    expect(launcherDispatchLabel({ dispatchId: "d", lastError: { code: "FUTURE_CODE" } }, "en")).toBe("Receipt unavailable");
    expect(launcherDispatchLabel({ dispatchId: "d", lastError: { message: "no code" } }, "zh")).toBe("回执暂不可用");
    expect(launcherDispatchReceiptLabel({ dispatchId: "d", lastError: { code: "RUNTIME_IDENTITY_MISMATCH" } }, "zh")).toBe("运行时身份不匹配");
    expect(launcherDispatchReceiptLabel({ dispatchId: "d", lastError: { code: "FUTURE_CODE" } }, "en")).toBe("Receipt unavailable");
    // Receipt statuses stay plain words; the classification only applies to a lastError.
    expect(launcherDispatchReceiptLabel({ dispatchId: "d", receipt: { status: "failed", error: { code: "TASK_NOT_FOUND" } } }, "zh")).toBe("失败");
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
  it("shows a persistent status read error despite a cached preference hiding ordinary pet status", async () => {
    await renderAssistant(undefined, { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
      settings: { ok: true, displayName: "助理", modelId: "m", preferences: {
        characterId: "dafeiyu", showStatus: false, showTitles: true, showCompletion: true, idleMessage: "",
      } } });
    expect(container?.querySelector('[role="status"]')?.hasAttribute("hidden")).toBe(true);
    bridge.getLauncherAssistantStatus.mockRejectedValue(new Error("status unavailable"));
    // One failed read stays a weak hint: the pill keeps obeying its preference.
    await act(async () => { await client?.refetchQueries({ queryKey: ["launcher-assistant", "status"], exact: true }); });
    await settle();
    expect(container?.querySelector('[role="status"]')?.hasAttribute("hidden")).toBe(true);
    expect(container?.textContent).not.toContain("个人助理暂不可用");
    // A second consecutive failure over a dead push channel escalates: the hard
    // degradation breaks through the hidden-status preference.
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
    const requestId = bridge.sendLauncherAssistantMessage.mock.calls[0][1];
    bridge.getLauncherAssistantDetail.mockResolvedValue({ id: "s", status: "ready", lastTurnTerminalTurnId: "turn-new", terminalReason: "success", messages: [
      { id: "native-user", role: "user", content: "hello", metadata: { clientSubmissionId: requestId, turnId: "turn-new" } },
      { id: "answer", role: "assistant", content: "done" },
    ] });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2100)); });
    await settle();
    expect(bridge.getLauncherAssistantDetail.mock.calls.length).toBeGreaterThan(initialReads);
    expect(conversation?.messages).toEqual([expect.objectContaining({ id: "native-user" }), expect.objectContaining({ id: "answer" })]);
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
    expect(conversation?.userDisplayName).toBe("操作者");
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
    const approve = [...(container?.querySelectorAll<HTMLButtonElement>('[role="dialog"] button') ?? [])].find(button => button.textContent?.endsWith("允许本次"));
    expect(approve).toBeTruthy();
    await act(async () => approve?.click());
    await settle();
    expect(bridge.resolveLauncherAssistantApproval).toHaveBeenCalledWith(request, "accept");
    expect(container?.textContent).toContain("decision unavailable");
    expect(container?.querySelector('[role="dialog"]')).toBeTruthy();
    bridge.resolveLauncherAssistantApproval.mockResolvedValueOnce({ ...request, status: "declined" });
    bridge.getLauncherAssistantApprovals.mockResolvedValue([]);
    await act(async () => [...(container?.querySelectorAll<HTMLButtonElement>('[role="dialog"] button') ?? [])].find(button => button.textContent?.endsWith("拒绝"))?.click());
    await settle();
    expect(bridge.resolveLauncherAssistantApproval).toHaveBeenLastCalledWith(request, "decline");
    expect(container?.querySelector('[role="dialog"]')).toBeNull();
  });
});

const RING_USAGE_DETAIL = {
  id: "s", status: "ready", messages: [], defaultFileContext: "",
  contextUsage: { used: 20_000, limit: 100_000, estimatedTokens: 20_000, messageCount: 4,
    userMessageCount: 2, assistantMessageCount: 2, toolCallCount: 0, source: "estimated" },
  lastContextComposition: { turnId: "t1", recordedAt: "2026-01-01T00:00:00Z", source: "assembly",
    totalChars: 0, totalTokens: 20_000, limitTokens: 100_000, segments: [
      { key: "history", label: "", chars: 0, tokens: 12_000, itemCount: 2, status: "observed", source: "history", description: "最近两轮" },
      { key: "system_prompt", label: "", chars: 0, tokens: 8_000, itemCount: 1, status: "observed", source: "prompt", description: "" },
    ] },
  lastCacheComposition: { turnId: "t1", recordedAt: "2026-01-01T00:00:00Z", source: "provider_usage",
    inputTokens: 10_000, cachedInputTokens: 8_000, cacheCreationInputTokens: 0, uncachedInputTokens: 2_000,
    cacheHitRate: 0.8, cacheUsageObserved: true, segments: [] },
  llmUsage: { source: "provider_usage", inputTokens: 10_000, outputTokens: 500, totalTokens: 10_500,
    cachedInputTokens: 8_000, cacheCreationInputTokens: 0, uncachedInputTokens: 2_000, cacheHitRate: 0.8,
    provider: "p", model: "m", recordedAt: "2026-01-01T00:00:00Z", tokensPerSecond: 42 },
} as unknown as SessionDetail;

describe("Launcher assistant composer surface model", () => {
  it("displays the bound dialogue model and says so when unset", () => {
    expect(launcherAssistantModelDisplay("test-model-x", "zh")).toBe("test-model-x");
    expect(launcherAssistantModelDisplay("  ", "zh")).toBe("未绑定模型");
    expect(launcherAssistantModelDisplay(undefined, "en")).toBe("No model bound");
  });

  it("backfills only user-authored non-empty text for the edit-as-new affordance", () => {
    expect(launcherAssistantEditBackfillDraft({ role: "user", content: "  帮我查天气  " })).toBe("  帮我查天气  ");
    expect(launcherAssistantEditBackfillDraft({ role: "assistant", content: "answer" })).toBeNull();
    expect(launcherAssistantEditBackfillDraft({ role: "user", content: "   " })).toBeNull();
  });

  it("returns no ring before any usage projection exists", () => {
    expect(launcherAssistantContextRing(undefined, "zh")).toBeNull();
    expect(launcherAssistantContextRing({ id: "s" } as SessionDetail, "zh")).toBeNull();
  });

  it("builds a read-only context ring from the native usage projections", () => {
    const ring = launcherAssistantContextRing(RING_USAGE_DETAIL, "zh");
    expect(ring?.usagePercent).toBe(20);
    expect(ring?.usedLabel).toBe("20K / 100K");
    expect(ring?.cacheState).toBe("observed");
    expect(ring?.cachedTokensLabel).toBe("8K");
    expect(ring?.hitPercent).toBe(80);
    expect(ring?.generationTokensPerSecond).toBe(42);
    // The launcher mounts neither the cache-diagnostics dialog nor the runtime
    // compression settings, so both handoffs stay off instead of dead ends.
    expect(ring?.detailAvailable).toBe(false);
    expect(ring?.autoCompact).toBeNull();
    expect(ring?.groups.map(group => group.key)).toEqual(["history", "prompt"]);
    expect(ring?.segments[0]?.contentPreview).toBe("最近两轮");
  });

  it("shows the bound model toolbar control and opens its model-connection settings", async () => {
    const openWorkbenchConfig = vi.fn().mockResolvedValue(undefined);
    (globalThis as { vibelutionLauncher?: unknown }).vibelutionLauncher = { openWorkbenchConfig };
    try {
      await renderAssistant(undefined, { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
        settings: { ok: true, displayName: "助理", modelId: "test-model-x",
          preferences: { characterId: "xiaoluo", showStatus: true, showTitles: true, showCompletion: false, idleMessage: "" } } });
      await showConversation();
      const row = container?.querySelector("[data-launcher-assistant-model-control]");
      expect(row?.textContent).toContain("test-model-x");
      await act(async () => row?.querySelector<HTMLButtonElement>("button")?.click());
      const settingsButton = [...document.querySelectorAll<HTMLButtonElement>("button")]
        .find(button => button.textContent?.includes("模型设置"));
      expect(settingsButton).toBeTruthy();
      await act(async () => settingsButton?.click());
      await settle();
      expect(openWorkbenchConfig).toHaveBeenCalledTimes(1);
    } finally {
      delete (globalThis as { vibelutionLauncher?: unknown }).vibelutionLauncher;
    }
  });

  it("switches the assistant model through the fixed bridge while preserving the composer", async () => {
    const status = { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" }, settings: { ok: true,
      modelId: "m1", displayName: "助理", modelChoices: [{ modelId: "m1", label: "模型一" }, { modelId: "m2", label: "模型二" }],
      preferences: { characterId: "xiaoluo", showStatus: true, showTitles: true, showCompletion: false, idleMessage: "" } } };
    await renderAssistant(undefined, status, undefined, { embedded: true });
    await act(async () => conversation?.onComposerChange("保留我的草稿"));
    bridge.setLauncherAssistantModel.mockResolvedValue({ modelId: "m2" });
    bridge.getLauncherAssistantStatus.mockResolvedValue({ ...status, settings: { ...status.settings, modelId: "m2" } });
    await act(async () => container?.querySelector<HTMLButtonElement>('[data-launcher-assistant-model-control] button')?.click());
    const selectTrigger = document.querySelector<HTMLButtonElement>('[role="combobox"][aria-label="切换助理模型"]')!;
    expect(selectTrigger.disabled).toBe(false);
    await act(async () => selectTrigger.click());
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(node => node.textContent === "模型二")!;
    await act(async () => option.click());
    await settle(); await settle();
    expect(bridge.setLauncherAssistantModel).toHaveBeenCalledWith("m2");
    expect(container?.querySelector('[data-launcher-assistant-model-control] button')?.textContent).toBe("模型二");
    expect(conversation?.composerValue).toBe("保留我的草稿");
    expect(bridge.sendLauncherAssistantMessage).not.toHaveBeenCalled();
  });

  it("loads earlier native history and retains it when the recent window refreshes", async () => {
    const messages = (start: number, end: number) => Array.from({ length: end - start + 1 }, (_, i) => ({ id: `s-message-${start + i}`, role: "user", content: String(start + i), timestamp: "2026-11-03T02:00:00Z" }));
    const page = (start: number, end: number) => ({ id: "s", status: "ready", currentPhase: "ready", activeBranchId: "branch", ledgerSeq: 5,
      defaultFileContext: "", messages: messages(start, end), messageWindow: { mode: "window", totalMessages: 260,
        returnedMessages: end - start + 1, oldestMessageIndex: start, newestMessageIndex: end, hasEarlier: start > 1,
        hasLater: end < 260, nextBeforeMessageIndex: start > 1 ? start : null, transcriptScope: "window" } });
    await renderAssistant(page(61, 260), undefined, undefined, { embedded: true });
    expect(conversation?.hasEarlierMessages).toBe(true);
    bridge.getLauncherAssistantDetail.mockImplementation((_session, cursor) => Promise.resolve(cursor === 61 ? page(1, 60) : page(61, 260)));
    await act(async () => conversation?.onLoadEarlierMessages?.());
    await settle(); await settle();
    expect(bridge.getLauncherAssistantDetail).toHaveBeenCalledWith("s", 61);
    expect(conversation?.messages[0].id).toBe("s-message-1");
    expect(conversation?.messages).toHaveLength(260);
    expect(conversation?.hasEarlierMessages).toBe(false);
    await click("刷新");
    expect(conversation?.messages[0].id).toBe("s-message-1");
    expect(conversation?.messages).toHaveLength(260);
  });

  it("projects the native context usage into the composer ring without a detail handoff", async () => {
    await renderAssistant(RING_USAGE_DETAIL as unknown as Record<string, unknown>);
    await showConversation();
    expect(conversation?.composerContextRing?.usagePercent).toBe(20);
    expect(conversation?.onOpenComposerContextDetail).toBeUndefined();
    expect(conversation?.turnModelControl).toBeUndefined();
    expect(conversation?.onOpenAgentModelConfig).toBeUndefined();
  });

  it("backfills the composer for edit-as-new without arming replacement semantics", async () => {
    const message = { id: "m1", role: "user", content: "帮我查天气", timestamp: "2026-01-01T00:00:00Z" } as ConversationMessage;
    await renderAssistant({ id: "s", status: "ready", messages: [message], defaultFileContext: "" });
    await showConversation();
    expect(conversation?.editUserMessageLabel).toBe("编辑为新消息");
    expect(conversation?.editingMessageId).toBeUndefined();
    await act(async () => conversation?.onEditUserMessage?.(message));
    await settle();
    expect(conversation?.composerValue).toBe("帮我查天气");
  });

  it("refuses edit backfill while a turn runs or the send is unconfirmed", async () => {
    const message = { id: "m1", role: "user", content: "帮我查天气", timestamp: "2026-01-01T00:00:00Z" } as ConversationMessage;
    await renderAssistant({ id: "s", status: "running", activeTurnId: "t1", messages: [message], defaultFileContext: "" });
    await showConversation();
    expect(conversation?.editUserMessageDisabled).toBe(true);
    await act(async () => conversation?.onEditUserMessage?.(message));
    await settle();
    expect(conversation?.composerValue).toBe("");
  });
});
