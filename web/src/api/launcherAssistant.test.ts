import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus,
  hideLauncherAssistant, launcherAssistantBridge, launcherConversationApi,
  sendLauncherAssistantMessage, setLauncherAssistantExpanded,
  getLauncherAssistantApprovals, resolveLauncherAssistantApproval,
  stopLauncherAssistantTurn, continueLauncherAssistantTurn,
} from "./launcherAssistant";
import type { SessionToolApprovalRequest } from "./types";

afterEach(() => vi.unstubAllGlobals());

describe("Launcher assistant bridge", () => {
  it("stops only the named turn and continues the native snapshot without arbitrary message", async () => {
    const continuation = { turnId: "old-turn", headId: "head", ledgerSeq: 8, agentId: "a" };
    const invoke = vi.fn().mockResolvedValueOnce({ id: "s", stopRequested: true })
      .mockResolvedValueOnce({ accepted: true, turnId: "new-turn", clientSubmissionId: "same-request" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await stopLauncherAssistantTurn("s", "running-turn");
    await expect(continueLauncherAssistantTurn(continuation, "same-request")).resolves.toEqual({ turnId: "new-turn" });
    expect(invoke.mock.calls).toEqual([[{ operation: "stop", turnId: "running-turn" }],
      [{ operation: "continue", requestId: "same-request", continuation }]]);
    invoke.mockResolvedValueOnce({ accepted: true, status: "queued", turnId: "", queuedTurnId: "queue" });
    await expect(continueLauncherAssistantTurn(continuation, "same-request")).rejects.toThrow("继续");
  });
  it("requires the dedicated Launcher bridge without a browser HTTP fallback", async () => {
    vi.stubGlobal("vibelutionLauncherAssistant", undefined);
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(() => launcherAssistantBridge({ vibelutionLauncher: { invoke: vi.fn() } })).toThrow("Launcher");
    await expect(getLauncherAssistantStatus()).rejects.toThrow("Launcher");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("accepts only the assistant identity and its own native detail", async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ assistant: { agentId: "a", directSessionId: "s", displayName: "助理" } })
      .mockResolvedValueOnce({ id: "s", messages: [] }).mockResolvedValueOnce({ id: "other", messages: [] });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantStatus()).resolves.toMatchObject({ assistant: { directSessionId: "s" } });
    await expect(getLauncherAssistantDetail("s")).resolves.toMatchObject({ id: "s" });
    await expect(getLauncherAssistantDetail("s")).rejects.toThrow("身份不一致");
    expect(invoke.mock.calls).toEqual([[{ operation: "status" }], [{ operation: "detail" }], [{ operation: "detail" }]]);
  });

  it("retries delivery with exactly the same message and stable request ID", async () => {
    const invoke = vi.fn().mockRejectedValueOnce(new Error("connection lost")).mockResolvedValueOnce({ accepted: true, turnId: "turn-1", secret: "omitted" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(sendLauncherAssistantMessage("hello", "stable-1")).rejects.toThrow("connection lost");
    await expect(sendLauncherAssistantMessage("hello", "stable-1")).resolves.toEqual({ turnId: "turn-1" });
    expect(invoke.mock.calls).toEqual(Array(2).fill([{ operation: "send", message: "hello", requestId: "stable-1" }]));
    await expect(sendLauncherAssistantMessage("hello", "")).rejects.toThrow("标识无效");
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it("keeps ambiguous acceptance unconfirmed instead of accepting an empty ack", async () => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue({ accepted: true }) });
    await expect(sendLauncherAssistantMessage("hello", "stable-1")).rejects.toThrow("轮次");
  });

  it.each([{ accepted: false, turnId: "native" }, { turnId: "native" }])("does not treat a turn ID alone as acceptance: %j", async value => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(value) });
    await expect(sendLauncherAssistantMessage("hello", "stable-1")).rejects.toThrow("轮次");
  });

  it("recognizes an explicit native queued ACK correlated to the unchanged request ID", async () => {
    const invoke = vi.fn().mockResolvedValue({ accepted: true, status: "queued", turnId: "", queuedTurnId: "queue-1", clientSubmissionId: "stable-1", queuePosition: 2 });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(sendLauncherAssistantMessage("hello", "stable-1")).resolves.toEqual({ turnId: "", queuedTurnId: "queue-1", clientSubmissionId: "stable-1" });
    expect(invoke).toHaveBeenCalledExactlyOnceWith({ operation: "send", message: "hello", requestId: "stable-1" });
  });

  it.each([
    { accepted: false }, { status: "running" }, { turnId: "native-turn" },
    { queuedTurnId: "" }, { clientSubmissionId: "other-request" }, { clientSubmissionId: undefined },
  ])("retains unknown delivery for an invalid queued ACK: %j", async patch => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue({ accepted: true, status: "queued", turnId: "", queuedTurnId: "queue-1", clientSubmissionId: "stable-1", ...patch }) });
    await expect(sendLauncherAssistantMessage("hello", "stable-1")).rejects.toThrow("队列");
  });

  it("reads status preferences and rejects malformed appearance values", async () => {
    const result = { assistant: { agentId: "a", directSessionId: "s", displayName: "助理" }, settings: {
      ok: true, displayName: "小洛", modelId: "m", preferences: { characterId: "xiaoluo", showStatus: false, showTitles: true, showCompletion: false, idleMessage: "hi" },
    } };
    const invoke = vi.fn().mockResolvedValueOnce(result).mockResolvedValueOnce({ ...result, settings: { ...result.settings, preferences: { ...result.settings.preferences, characterId: "unknown" } } });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantStatus()).resolves.toEqual(result);
    await expect(getLauncherAssistantStatus()).rejects.toThrow("外观");
  });

  it.each(["default", "circle", "spark", "codex", "minimal", "initial"])("accepts canonical operator avatar %s without changing assistant identity", async avatarPreset => {
    const result = { assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" }, operatorProfile: { displayName: "", avatarPreset } };
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(result) });
    await expect(getLauncherAssistantStatus()).resolves.toEqual(result);
  });

  it("counts the operator name by Unicode characters like the native config owner", async () => {
    const result = { assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" },
      operatorProfile: { displayName: "🙂".repeat(120), avatarPreset: "initial" } };
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(result) });
    await expect(getLauncherAssistantStatus()).resolves.toEqual(result);
  });

  it.each([
    null, [], {}, { displayName: "Operator" }, { displayName: "Operator", avatarPreset: "SPARK" },
    { displayName: 42, avatarPreset: "spark" }, { displayName: "x".repeat(121), avatarPreset: "spark" },
    { displayName: "🙂".repeat(121), avatarPreset: "initial" },
    { displayName: "line\nfeed", avatarPreset: "spark" }, { displayName: "control\u007f", avatarPreset: "spark" },
    { displayName: "Operator", avatarPreset: false }, { displayName: "Operator", avatarPreset: "spark", bio: "PRIVATE_SENTINEL" },
    { displayName: "Operator", avatarPreset: "spark", avatarImageUrl: "/private/file" },
  ])("rejects a malformed or expanded optional operator profile: %j", async operatorProfile => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue({ assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" }, operatorProfile }) });
    await expect(getLauncherAssistantStatus()).rejects.toThrow("operator profile");
  });

  it("limits approval transport to the owned session and once-only decisions", async () => {
    const request = { requestId: "r", sessionId: "s", turnId: "t", agentId: "a", toolName: "command_tool", status: "pending", risk: "high", argumentSummary: { command: "pwd" }, availableDecisions: ["accept", "decline", "acceptAlways"] } as SessionToolApprovalRequest;
    const resolved = { ...request, status: "accepted" };
    const invoke = vi.fn().mockResolvedValueOnce([request]).mockResolvedValueOnce([{ ...request, sessionId: "other" }])
      .mockResolvedValueOnce(resolved).mockResolvedValueOnce({ ...resolved, turnId: "wrong" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantApprovals("s")).resolves.toEqual([request]);
    await expect(getLauncherAssistantApprovals("s")).rejects.toThrow("身份不一致");
    await expect(resolveLauncherAssistantApproval(request, "acceptAlways" as "accept")).rejects.toThrow("不可用");
    await expect(resolveLauncherAssistantApproval(request, "accept")).resolves.toEqual(resolved);
    expect(invoke.mock.calls[2]).toEqual([{ operation: "resolveApproval", requestId: "r", decision: "accept" }]);
    await expect(resolveLauncherAssistantApproval(request, "decline")).rejects.toThrow("未确认");
  });

  it("uses explicit resize/hide operations and preserves native receipt status", async () => {
    const row = { dispatchId: "d", receipt: { status: "ready" } };
    const invoke = vi.fn().mockResolvedValueOnce({ expanded: true }).mockResolvedValueOnce({ expanded: true })
      .mockResolvedValueOnce({ dispatches: [row] }).mockResolvedValueOnce({ hidden: true });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await setLauncherAssistantExpanded(true);
    await expect(setLauncherAssistantExpanded(false)).rejects.toThrow("调整");
    await expect(getLauncherAssistantDispatches()).resolves.toEqual([row]);
    await hideLauncherAssistant();
    expect(invoke.mock.calls.at(-1)).toEqual([{ operation: "hide" }]);
  });

  it("routes native conversation config and curation through the same bridge", async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ language: "zh", modelLabels: {} })
      .mockResolvedValueOnce({ sessionId: "s", items: [] })
      .mockResolvedValueOnce({ sessionId: "s", messageId: "m", action: "include" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await launcherConversationApi.fetchConfigBootstrap();
    await launcherConversationApi.fetchMessageCuration("s");
    await launcherConversationApi.setMessageCuration("s", "m", "include");
    expect(invoke.mock.calls).toEqual([
      [{ operation: "config" }], [{ operation: "curation", sessionId: "s" }],
      [{ operation: "curate", sessionId: "s", messageId: "m", action: "include" }],
    ]);
  });

  it.each([[], null, {}, { language: "fr" }])("rejects invalid native bootstrap data: %j", async value => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(value) });
    await expect(launcherConversationApi.fetchConfigBootstrap()).rejects.toThrow("Launcher 配置");
  });
});
