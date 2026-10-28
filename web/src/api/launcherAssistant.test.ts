import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus,
  hideLauncherAssistant, launcherAssistantBridge, launcherConversationApi,
  sendLauncherAssistantMessage, setLauncherAssistantExpanded,
  getLauncherAssistantApprovals, resolveLauncherAssistantApproval,
  previewLauncherDispatchApproval, decideLauncherDispatchApproval, declineLauncherDispatchSummary,
  stopLauncherAssistantTurn, continueLauncherAssistantTurn,
  getLauncherOperatorAsset, openLauncherFromAssistant,
} from "./launcherAssistant";
import type { SessionToolApprovalRequest } from "./types";

afterEach(() => vi.unstubAllGlobals());

describe("Launcher window entry", () => {
  it("uses only the closed IPC verb and accepts native cancellation", async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ opened: true }).mockResolvedValueOnce({ opened: false });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(openLauncherFromAssistant()).resolves.toBe(true);
    await expect(openLauncherFromAssistant()).resolves.toBe(false);
    expect(invoke.mock.calls).toEqual([[{ operation: "openLauncher" }], [{ operation: "openLauncher" }]]);
  });
  it.each([{}, { opened: "true" }, { opened: true, path: "private" }])("rejects an unknown window result", async result => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(result) });
    await expect(openLauncherFromAssistant()).rejects.toThrow("Launcher");
  });
});

describe("Launcher operator assets", () => {
  const image = { contentType: "image/png", dataBase64: "AQI=", sha256: "a".repeat(64) };
  const response = { schemaVersion: 1, kind: "avatar", image, readability: "standard" };

  it("reads only the fixed kind through IPC and returns a data image without raw image fields", async () => {
    const invoke = vi.fn().mockResolvedValue(response);
    const fetch = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke }); vi.stubGlobal("fetch", fetch);
    await expect(getLauncherOperatorAsset("avatar")).resolves.toEqual({ schemaVersion: 1, kind: "avatar", readability: "standard",
      image: { url: "data:image/png;base64,AQI=", sha256: image.sha256 } });
    expect(invoke).toHaveBeenCalledExactlyOnceWith({ operation: "operatorAsset", kind: "avatar" });
    expect(fetch).not.toHaveBeenCalled();
    await expect(getLauncherOperatorAsset("https://example.test/image.png" as "avatar")).rejects.toThrow("类型");
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it.each(["image/png", "image/jpeg", "image/webp"])("accepts the fixed image MIME %s", async contentType => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue({ ...response, image: { ...image, contentType } }) });
    expect((await getLauncherOperatorAsset("avatar")).image?.url.startsWith(`data:${contentType};base64,`)).toBe(true);
  });

  it("accepts cleared images and closed readability values", async () => {
    for (const readability of ["soft", "standard", "strong"]) {
      vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue({ ...response, image: null, readability }) });
      expect((await getLauncherOperatorAsset("avatar")).image).toBeNull();
    }
  });

  const invalidResponses = [
    ["version", { ...response, schemaVersion: 2 }], ["wrong kind", { ...response, kind: "background" }],
    ["root extras", { ...response, url: "https://example.test" }], ["readability", { ...response, readability: "other" }],
    ["readability type", { ...response, readability: ["standard"] }],
    ["MIME type", { ...response, image: { ...image, contentType: ["image/png"] } }],
    ["SVG", { ...response, image: { ...image, contentType: "image/svg+xml" } }],
    ["URL image", { ...response, image: { url: "https://example.test" } }],
    ["image extras", { ...response, image: { ...image, path: "C:/secret.png" } }],
    ["hash", { ...response, image: { ...image, sha256: "broken" } }],
    ...["", "AQI", "AQI===", "AQ I=", "AQI=\n", "AQI_", "ＡQI=", "AR==", "AQJ=", "data:image/png;base64,AQI=", "===="].map(dataBase64 =>
      [`base64 ${dataBase64.length}`, { ...response, image: { ...image, dataBase64 } }]),
  ] as const;
  it.each(invalidResponses)("rejects malformed resource: %s", async (_label, value) => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(value) });
    await expect(getLauncherOperatorAsset("avatar")).rejects.toThrow("图片资源不可用");
  });

  it.each(["avatar", "background"] as const)("checks the decoded size boundary for %s without exposing bytes", async kind => {
    const limit = (kind === "avatar" ? 5 : 10) * 1024 * 1024;
    const encode = (length: number) => "AAAA".repeat(Math.floor(length / 3)) + (length % 3 === 1 ? "AA==" : length % 3 === 2 ? "AAA=" : "");
    const invoke = vi.fn().mockResolvedValue({ ...response, kind, image: { ...image, dataBase64: encode(limit) } });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const result = await getLauncherOperatorAsset(kind);
    expect(Boolean(result.image)).toBe(true);
    invoke.mockResolvedValue({ ...response, kind, image: { ...image, dataBase64: encode(limit + 1) } });
    await expect(getLauncherOperatorAsset(kind)).rejects.toThrow("图片资源不可用");
  });

  it("honors abort before and after native IPC", async () => {
    const controller = new AbortController();
    const invoke = vi.fn(async () => { controller.abort(); return response; });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherOperatorAsset("avatar", { signal: controller.signal })).rejects.toThrow();
    expect(invoke).toHaveBeenCalledTimes(1);
    await expect(getLauncherOperatorAsset("avatar", { signal: controller.signal })).rejects.toThrow();
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("keeps old status compatible and rejects unsupported or malformed capability versions", async () => {
    const assistant = { agentId: "a", directSessionId: "s", displayName: "Assistant" };
    const invoke = vi.fn().mockResolvedValue({ assistant });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    expect((await getLauncherAssistantStatus()).operatorAssetsVersion).toBeUndefined();
    invoke.mockResolvedValue({ assistant, operatorAssetsVersion: 1 });
    expect((await getLauncherAssistantStatus()).operatorAssetsVersion).toBe(1);
    for (const operatorAssetsVersion of [undefined, null, "1", 0, 2]) {
      invoke.mockResolvedValue({ assistant, operatorAssetsVersion });
      await expect(getLauncherAssistantStatus()).rejects.toThrow("版本");
    }
  });
});

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

  it("binds preview and decision to the observed task and rejects mismatched results", async () => {
    const approval = { approvalId: "approval-1", toolName: "write_file_tool", risk: "write", targetSummary: { pathPreview: "x" }, revision: "fp-1", availableDecisions: ["accept", "decline"] };
    const row = { dispatchId: "dispatch-1", agentId: "worker", nativeTaskId: "task-1", receipt: { taskId: "task-1", pendingApprovals: [approval] } };
    const preview = { taskId: "task-1", sessionId: "s", agentId: "worker", requestId: "approval-1", turnId: "t", callId: "c", toolName: "write_file_tool", revision: "a".repeat(64), approval: "always", risk: "write", permissionPreset: "request_approval", decisionFingerprint: "f", configRevision: 1, configHash: "h", argumentsJson: "{}", executionArgumentsJson: "{}" };
    const invoke = vi.fn().mockResolvedValueOnce(preview).mockResolvedValueOnce({ dispatchId: "dispatch-1", taskId: "task-1", approvalId: "approval-1", revision: preview.revision, decision: "accept" }).mockResolvedValueOnce({ ...preview, agentId: "other" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const actual = await previewLauncherDispatchApproval(row, approval);
    await decideLauncherDispatchApproval(row, approval, actual, "accept");
    expect(invoke).toHaveBeenCalledWith({ operation: "decideDispatchApproval", dispatchId: "dispatch-1", taskId: "task-1", approvalId: "approval-1", revision: "a".repeat(64), decision: "accept" });
    await expect(decideLauncherDispatchApproval(row, { ...approval }, actual, "decline")).rejects.toThrow("已变化");
    await expect(previewLauncherDispatchApproval(row, approval)).rejects.toThrow("不可核对");
  });

  it("fails closed on malformed or mismatched target approval receipts", async () => {
    const approval = { approvalId: "a", toolName: "exec_command", risk: "write", targetSummary: {}, revision: "fp", availableDecisions: ["decline"] };
    const invoke = vi.fn().mockResolvedValueOnce({ dispatches: [{ dispatchId: "d", nativeTaskId: "t", receipt: { taskId: "other", pendingApprovals: [approval] } }] })
      .mockResolvedValueOnce({ dispatches: [{ dispatchId: "d", nativeTaskId: "t", receipt: { taskId: "t", pendingApprovals: [{ ...approval, targetSummary: null }] } }] });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantDispatches()).rejects.toThrow("暂不可用");
    await expect(getLauncherAssistantDispatches()).rejects.toThrow("暂不可用");
  });

  it("only declines a matching summary with a nonempty revision", async () => {
    const approval = { approvalId: "a", toolName: "exec_command", risk: "write", targetSummary: {}, revision: "policy-1", availableDecisions: ["decline"] };
    const row = { dispatchId: "d", nativeTaskId: "t", receipt: { taskId: "t", pendingApprovals: [approval] } };
    const invoke = vi.fn().mockResolvedValue({ dispatchId: "d", nativeTaskId: "t" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await declineLauncherDispatchSummary(row, approval);
    expect(invoke).toHaveBeenCalledWith({ operation: "declineDispatchApproval", dispatchId: "d", taskId: "t", approvalId: "a", revision: "policy-1" });
    const empty = { ...approval, revision: "" };
    await expect(declineLauncherDispatchSummary({ ...row, receipt: { ...row.receipt, pendingApprovals: [empty] } }, empty)).rejects.toThrow("已变化");
    await expect(declineLauncherDispatchSummary(row, { ...approval })).rejects.toThrow("已变化");
    expect(invoke).toHaveBeenCalledTimes(1);
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
