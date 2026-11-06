import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus, getLauncherAssistantTeamRuns,
  hideLauncherAssistant, launcherAssistantBridge, launcherConversationApi,
  sendLauncherAssistantMessage, setLauncherAssistantExpanded, setLauncherAssistantModel,
  getLauncherAssistantApprovals, resolveLauncherAssistantApproval,
  previewLauncherDispatchApproval, decideLauncherDispatchApproval, declineLauncherDispatchSummary,
  stopLauncherAssistantTurn, continueLauncherAssistantTurn, switchLauncherAssistantHead,
  regenerateLauncherAssistantMessage, guideLauncherAssistantTurn,
  getLauncherOperatorAsset, getLauncherAssistantAvatar, openLauncherFromAssistant,
  subscribeLauncherAssistantSessionEvent,
  uploadLauncherUserSecret,
  setLauncherManagementPermissionPreset,
  getLauncherAssistantBudget, setLauncherAssistantBudget,
  getLauncherAssistantUsageSummary,
  updateLauncherAssistantQueuedTurn, removeLauncherAssistantQueuedTurn, sendNowLauncherAssistantQueuedTurn,
  LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE,
} from "./launcherAssistant";
import type { SessionToolApprovalRequest } from "./types";

afterEach(() => vi.unstubAllGlobals());

describe("operator continuation send", () => {
  it.each(["ASSISTANT_IDENTITY_INVALID", "Error invoking remote method 'assistant:request': Error: ASSISTANT_IDENTITY_INVALID"])("treats %s as pre-admission only for a bound continuation", async message => {
    const invoke = vi.fn().mockRejectedValue(new Error(message));
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const expected = { agentId: "a", sessionId: "s", turnId: "t", headId: "h", ledgerSeq: 5 };
    await expect(sendLauncherAssistantMessage(LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE, "original", [], [], expected)).rejects.toMatchObject({ name: "LauncherAssistantRejectedError" });
    await expect(sendLauncherAssistantMessage("normal send", "ordinary")).rejects.toMatchObject({ name: "Error", message });
  });
  it("preserves the exact native snapshot and rejects arbitrary content or attachments before IPC", async () => {
    const invoke = vi.fn().mockResolvedValue({ accepted: true, turnId: "next" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const expected = { agentId: "a", sessionId: "s", turnId: "t", headId: "h", ledgerSeq: 5 };
    await expect(sendLauncherAssistantMessage(LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE, "original", [], [], expected)).resolves.toEqual({ turnId: "next" });
    expect(invoke).toHaveBeenCalledWith({ operation: "send", message: LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE, requestId: "original", controlContinuation: expected });
    for (const send of [() => sendLauncherAssistantMessage("changed", "original", [], [], expected),
      () => sendLauncherAssistantMessage(LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE, "original", ["file"], [], expected),
      () => sendLauncherAssistantMessage(LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE, "original", [], [], { ...expected, ledgerSeq: 0 })]) await expect(send()).rejects.toThrow();
    expect(invoke).toHaveBeenCalledOnce();
  });
});

function usageSnapshot() {
  const numbers = { inputTokens: 100, cachedInputTokens: 0, cacheReadInputTokens: 0, cacheCreationInputTokens: 0,
    uncachedInputTokens: 100, outputTokens: 0, reasoningOutputTokens: 0, totalTokens: 100, latencyMs: 0,
    cacheHitRate: 0, cacheUsageObserved: true, cacheUsageMissingReason: "" };
  return { sessionId: "s", agentId: "a", lastTokenUsage: { ...numbers, source: "provider_usage" },
    sessionTokenUsage: { ...numbers, callCount: 1, observedCallCount: 1, estimatedCallCount: 0, missingCallCount: 0,
      notCalledCount: 0, cacheObservedInputTokens: 100, cacheObservedCallCount: 1, cacheUnobservedCallCount: 0,
      cacheUsageComplete: true } };
}

describe("Launcher assistant usage snapshot", () => {
  it("uses only the native parameterless operation and preserves zero, missing and partial data", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const zero = usageSnapshot();
    const missing = { ...zero, lastTokenUsage: { ...zero.lastTokenUsage, cacheUsageObserved: false,
      cacheUsageMissingReason: "provider_cache_usage_missing" }, sessionTokenUsage: { ...zero.sessionTokenUsage,
      cacheObservedCallCount: 0, cacheObservedInputTokens: 0, cacheUnobservedCallCount: 1,
      cacheUsageObserved: false, cacheUsageComplete: false, cacheUsageMissingReason: "provider_cache_usage_missing" } };
    const partial = { ...zero, sessionTokenUsage: { ...zero.sessionTokenUsage, cacheUnobservedCallCount: 1,
      cacheUsageComplete: false, cacheUsageMissingReason: "partial_provider_cache_usage" } };
    for (const snapshot of [zero, missing, partial]) {
      invoke.mockResolvedValueOnce(snapshot);
      await expect(getLauncherAssistantUsageSummary()).resolves.toEqual(snapshot);
      expect(invoke).toHaveBeenLastCalledWith({ operation: "usageSummary" });
    }
    invoke.mockRejectedValueOnce(new Error("ASSISTANT_USAGE_UNAVAILABLE"));
    await expect(getLauncherAssistantUsageSummary()).rejects.toThrow("ASSISTANT_USAGE_UNAVAILABLE");
    expect(invoke).toHaveBeenCalledTimes(4);
  });

  it("rejects overbroad or malformed snapshots at the renderer boundary", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const snapshot = usageSnapshot();
    for (const invalid of [null, [], { ...snapshot, globalTokenUsage: {} }, { ...snapshot, sessionId: "../other" },
      { ...snapshot, lastTokenUsage: { ...snapshot.lastTokenUsage, ledgerPath: "private" } },
      { ...snapshot, lastTokenUsage: { ...snapshot.lastTokenUsage, cacheUsageObserved: "false" } },
      { ...snapshot, lastTokenUsage: { ...snapshot.lastTokenUsage, source: ["provider_usage"] } },
      { ...snapshot, sessionTokenUsage: { ...snapshot.sessionTokenUsage, cacheHitRate: NaN } },
      { ...snapshot, sessionTokenUsage: { ...snapshot.sessionTokenUsage, cachedInputTokens: true } }]) {
      invoke.mockResolvedValueOnce(invalid);
      await expect(getLauncherAssistantUsageSummary()).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    }
  });
});

describe("Launcher assistant native queue API", () => {
  const assistant = { agentId: "assistant-one", directSessionId: "session-one", displayName: "Assistant" };
  const row = { id: "queued-one", position: 1, status: "queued", content: "next task", kind: "user",
    attachments: [{ artifactId: "native-file", filename: "note.txt" }], references: [], nativeExtra: { retained: true } };
  const commands = [
    { operation: "updateQueuedTurn", call: (sessionId: string, queuedTurnId: string) =>
      updateLauncherAssistantQueuedTurn(sessionId, queuedTurnId, { content: "edited" }) },
    { operation: "removeQueuedTurn", call: removeLauncherAssistantQueuedTurn },
    { operation: "sendNowQueuedTurn", call: sendNowLauncherAssistantQueuedTurn },
  ] as const;

  it("keeps old hosts compatible and advertises queue support only at version one", async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ assistant }).mockResolvedValueOnce({ assistant, followupQueueVersion: 1 });
    const fetch = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke }); vi.stubGlobal("fetch", fetch);
    expect((await getLauncherAssistantStatus()).followupQueueVersion).toBeUndefined();
    expect((await getLauncherAssistantStatus()).followupQueueVersion).toBe(1);
    expect(invoke.mock.calls).toEqual([[{ operation: "status" }], [{ operation: "status" }]]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects malformed or unsupported queue capability versions", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    for (const followupQueueVersion of [null, true, false, 0, 2, "1", [], {}]) {
      invoke.mockResolvedValueOnce({ assistant, followupQueueVersion });
      await expect(getLauncherAssistantStatus()).rejects.toThrow("队列版本不可用");
    }
  });

  it("uses only session-scoped IPC and preserves native rows and send-now stop acknowledgements", async () => {
    const invoke = vi.fn().mockResolvedValue({ queuedTurns: [row] });
    const fetch = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke }); vi.stubGlobal("fetch", fetch);
    const update = { content: "edited", position: 2, status: "paused" } as const;
    await expect(updateLauncherAssistantQueuedTurn("session-one", "queued-one", update)).resolves.toEqual([row]);
    expect(invoke).toHaveBeenLastCalledWith({ operation: "updateQueuedTurn", sessionId: "session-one", queuedTurnId: "queued-one", ...update });
    await expect(removeLauncherAssistantQueuedTurn("session-one", "queued-one")).resolves.toEqual([row]);
    expect(invoke).toHaveBeenLastCalledWith({ operation: "removeQueuedTurn", sessionId: "session-one", queuedTurnId: "queued-one" });
    for (const stopRequested of [true, false]) {
      const receipt = { queuedTurns: [row], stopRequested };
      invoke.mockResolvedValueOnce(receipt);
      await expect(sendNowLauncherAssistantQueuedTurn("session-one", "queued-one", { expectedTurnId: "observed-turn" }))
        .resolves.toEqual(receipt);
      expect(invoke).toHaveBeenLastCalledWith({ operation: "sendNowQueuedTurn", sessionId: "session-one", queuedTurnId: "queued-one", expectedTurnId: "observed-turn" });
    }
    invoke.mockResolvedValueOnce({ queuedTurns: [] });
    await expect(removeLauncherAssistantQueuedTurn("session-one", "queued-one")).resolves.toEqual([]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("omits undefined fields and keeps valid content and ID boundaries without coercion", async () => {
    const invoke = vi.fn().mockResolvedValue({ queuedTurns: [row] });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await updateLauncherAssistantQueuedTurn("s", "q", { content: undefined, position: undefined, status: "queued" });
    expect(invoke).toHaveBeenLastCalledWith({ operation: "updateQueuedTurn", sessionId: "s", queuedTurnId: "q", status: "queued" });
    for (const content of ["", " ", "x".repeat(64000)]) {
      await updateLauncherAssistantQueuedTurn("s".repeat(160), "q".repeat(160), { content });
      expect(invoke).toHaveBeenLastCalledWith({ operation: "updateQueuedTurn", sessionId: "s".repeat(160), queuedTurnId: "q".repeat(160), content });
    }
    await updateLauncherAssistantQueuedTurn("s", "q", { position: Number.MAX_SAFE_INTEGER });
    expect(invoke).toHaveBeenLastCalledWith({ operation: "updateQueuedTurn", sessionId: "s", queuedTurnId: "q", position: Number.MAX_SAFE_INTEGER });
    invoke.mockResolvedValue({ queuedTurns: [], stopRequested: false });
    await sendNowLauncherAssistantQueuedTurn("s", "q", { expectedTurnId: undefined });
    expect(invoke).toHaveBeenLastCalledWith({ operation: "sendNowQueuedTurn", sessionId: "s", queuedTurnId: "q" });
    await sendNowLauncherAssistantQueuedTurn("s", "q", { expectedTurnId: "t".repeat(160) });
    expect(invoke).toHaveBeenLastCalledWith({ operation: "sendNowQueuedTurn", sessionId: "s", queuedTurnId: "q", expectedTurnId: "t".repeat(160) });
  });

  it("rejects invalid Session and queue IDs before invoking any native command", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    for (const { call } of commands) {
      for (const invalid of [undefined, null, true, 7, "", "../other", "has space", "id.one", "id:one", "one\n", "one\r", "x".repeat(161)]) {
        await expect(call(invalid as string, "queued-one")).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
        await expect(call("session-one", invalid as string)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
      }
    }
    expect(invoke).not.toHaveBeenCalled();
  });

  it("rejects empty updates, identity injection and invalid mutation fields before IPC", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const invalidPayloads: unknown[] = [undefined, null, [], true, "edit", {}, { content: undefined },
      { content: undefined, position: undefined, status: undefined }, { content: null }, { content: true },
      { content: "x".repeat(64001) }, { position: null }, { position: true }, { position: "1" },
      { position: 0 }, { position: -1 }, { position: 1.5 }, { position: NaN }, { position: Number.MAX_SAFE_INTEGER + 1 },
      { status: null }, { status: true }, { status: "starting" }, { status: "queued\n" },
      { content: "edited", sessionId: "foreign" }, { content: "edited", queuedTurnId: "other" },
      { content: "edited", projectRoot: "private" }, { content: "edited", extra: undefined }];
    for (const payload of invalidPayloads)
      await expect(updateLauncherAssistantQueuedTurn("session-one", "queued-one", payload as Parameters<typeof updateLauncherAssistantQueuedTurn>[2]))
        .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(invoke).not.toHaveBeenCalled();
  });

  it("rejects malformed expected turn IDs and extra send-now fields before IPC", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    for (const expectedTurnId of [null, true, false, 7, [], {}, "", "../other", "has space", "id.one", "id:one", "one\n", "t".repeat(161)])
      await expect(sendNowLauncherAssistantQueuedTurn("session-one", "queued-one", { expectedTurnId: expectedTurnId as string }))
        .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    for (const payload of [null, [], true, { sessionId: "foreign" }, { queuedTurnId: "other" }, { content: "injected" }, { expectedTurnId: "turn", extra: undefined }])
      await expect(sendNowLauncherAssistantQueuedTurn("session-one", "queued-one", payload as Parameters<typeof sendNowLauncherAssistantQueuedTurn>[2]))
        .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(invoke).not.toHaveBeenCalled();
  });

  it("rejects malformed native receipts and preserves row extensions only inside valid rows", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const invalidReceipts: unknown[] = [undefined, null, [], {}, { queuedTurns: null }, { queuedTurns: {} },
      { queuedTurns: [null] }, { queuedTurns: [[]] }, { queuedTurns: [{}] },
      ...[{ id: "" }, { id: "../other" }, { id: "queued-one\n" }, { id: "q".repeat(161) }, { id: true },
        { position: 0 }, { position: -1 }, { position: 1.5 }, { position: true }, { position: Number.MAX_SAFE_INTEGER + 1 },
        { status: "" }, { status: false }, { content: null }].map(fields => ({ queuedTurns: [{ ...row, ...fields }] })),
      { queuedTurns: [row], sessionId: "foreign" }, { queuedTurns: [row], privatePath: "private" }];
    for (const { operation, call } of commands) {
      for (const receipt of invalidReceipts) {
        invoke.mockResolvedValueOnce(operation === "sendNowQueuedTurn" && receipt && typeof receipt === "object" && !Array.isArray(receipt)
          ? { ...receipt, stopRequested: true } : receipt);
        await expect(call("session-one", "queued-one")).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
      }
    }
    for (const { operation, call } of commands) {
      if (operation === "sendNowQueuedTurn") continue;
      invoke.mockResolvedValueOnce({ queuedTurns: [row], stopRequested: false });
      await expect(call("session-one", "queued-one")).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    }
  });

  it("requires an actual boolean send-now acknowledgement", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    for (const stopRequested of [undefined, null, 0, 1, "false", [], {}]) {
      invoke.mockResolvedValueOnce({ queuedTurns: [row], stopRequested });
      await expect(sendNowLauncherAssistantQueuedTurn("session-one", "queued-one")).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    }
  });

  it("never falls back to HTTP when the dedicated assistant IPC is unavailable", async () => {
    vi.stubGlobal("vibelutionLauncherAssistant", undefined);
    vi.stubGlobal("vibelutionLauncher", { invoke: vi.fn() });
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    for (const { call } of commands) await expect(call("session-one", "queued-one")).rejects.toThrow("Launcher");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("propagates a failed native mutation once without replaying or fetching", async () => {
    const invoke = vi.fn().mockRejectedValue(new Error("ASSISTANT_SESSION_CONFLICT"));
    const fetch = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke }); vi.stubGlobal("fetch", fetch);
    for (const { call } of commands) await expect(call("session-one", "queued-one")).rejects.toThrow("ASSISTANT_SESSION_CONFLICT");
    expect(invoke).toHaveBeenCalledTimes(3);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("Launcher assistant budget contract", () => {
  it("reads and saves zero, default and custom quotas through the fixed bridge", async () => {
    const invoke = vi.fn().mockResolvedValue({ revision: 3, maxCallsPerTurn: 16 });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantBudget()).resolves.toEqual({ revision: 3, maxCallsPerTurn: 16 });
    expect(invoke).toHaveBeenLastCalledWith({ operation: "budgetParameters" });
    for (const maxCallsPerTurn of [0, null, 32]) {
      invoke.mockResolvedValueOnce({ revision: 4, maxCallsPerTurn });
      await expect(setLauncherAssistantBudget({ revision: 3, maxCallsPerTurn })).resolves.toEqual({ revision: 4, maxCallsPerTurn });
      expect(invoke).toHaveBeenLastCalledWith({ operation: "setBudgetParameters", revision: 3, maxCallsPerTurn });
    }
    const calls = invoke.mock.calls.length;
    await expect(setLauncherAssistantBudget({ revision: 3, maxCallsPerTurn: -1 })).rejects.toThrow("ASSISTANT_BUDGET_INVALID");
    expect(invoke).toHaveBeenCalledTimes(calls);
    invoke.mockRejectedValueOnce(new Error("ASSISTANT_BUDGET_CONFLICT"));
    await expect(setLauncherAssistantBudget({ revision: 3, maxCallsPerTurn: 0 })).rejects.toThrow("ASSISTANT_BUDGET_CONFLICT");
    expect(invoke).toHaveBeenCalledTimes(calls + 1);
    invoke.mockResolvedValueOnce({ revision: 4, maxCallsPerTurn: 16 });
    await expect(setLauncherAssistantBudget({ revision: 3, maxCallsPerTurn: 0 })).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
  });
});

describe("Launcher management-permission contract", () => {
  it("writes through native CAS once and rejects invalid inputs and malformed receipts", async () => {
    const invoke = vi.fn().mockResolvedValue({ preset: "full_access", revision: 4 });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(setLauncherManagementPermissionPreset("full_access", 3)).resolves.toEqual({ preset: "full_access", revision: 4 });
    expect(invoke).toHaveBeenCalledExactlyOnceWith({ operation: "setManagementPermissionPreset", preset: "full_access", expectedRevision: 3 });
    for (const revision of [true, -1, 0.5, Number.MAX_SAFE_INTEGER + 1, NaN])
      await expect(setLauncherManagementPermissionPreset("auto_review", revision as number)).rejects.toThrow("ASSISTANT_PERMISSION_INVALID");
    expect(invoke).toHaveBeenCalledTimes(1);
    for (const receipt of [{ preset: "auto_review", revision: 4 }, { preset: "full_access", revision: true },
      { preset: "full_access", revision: 2 }, { preset: "full_access", revision: 5 }, { preset: "full_access", revision: 4, extra: true }]) {
      invoke.mockResolvedValueOnce(receipt);
      await expect(setLauncherManagementPermissionPreset("full_access", 3)).rejects.toThrow("ASSISTANT_RESPONSE_INVALID");
    }
    invoke.mockRejectedValueOnce(new Error("ASSISTANT_PERMISSION_CONFLICT"));
    const calls = invoke.mock.calls.length;
    await expect(setLauncherManagementPermissionPreset("full_access", 3)).rejects.toThrow("ASSISTANT_PERMISSION_CONFLICT");
    expect(invoke).toHaveBeenCalledTimes(calls + 1);
  });

  it("requires exactly a known preset and safe nonnegative revision in status", async () => {
    const status = { assistant: { agentId: "a", directSessionId: "s", displayName: "PA" }, settings: {
      ok: true, preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" },
      displayName: "PA", modelId: "model" } };
    const invoke = vi.fn().mockResolvedValue(status);
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantStatus()).resolves.toEqual(status);
    for (const managementPermission of [null, {}, { preset: "custom", revision: 0 }, { preset: "auto_review", revision: true },
      { preset: "auto_review", revision: -1 }, { preset: "auto_review", revision: 0.5 },
      { preset: "auto_review", revision: Number.MAX_SAFE_INTEGER + 1 }, { preset: "auto_review", revision: 0, extra: true }]) {
      invoke.mockResolvedValueOnce({ ...status, settings: { ...status.settings, managementPermission } });
      await expect(getLauncherAssistantStatus()).rejects.toThrow("操作权限不可用");
    }
    const valid = { ...status, settings: { ...status.settings, managementPermission: { preset: "request_approval", revision: 0 } } };
    invoke.mockResolvedValueOnce(valid);
    await expect(getLauncherAssistantStatus()).resolves.toEqual(valid);
  });
});

describe("Launcher assistant model controls", () => {
  it("switches through the closed invoke bridge and verifies the observed binding", async () => {
    const invoke = vi.fn().mockResolvedValue({ modelId: "local/other" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(setLauncherAssistantModel("local/other")).resolves.toEqual({ modelId: "local/other" });
    expect(invoke).toHaveBeenCalledExactlyOnceWith({ operation: "setModel", modelId: "local/other" });
    invoke.mockResolvedValueOnce({ modelId: "wrong" });
    await expect(setLauncherAssistantModel("local/other")).rejects.toThrow("切换尚未确认");
    invoke.mockRejectedValueOnce(new Error("ASSISTANT_MODEL_BUSY"));
    await expect(setLauncherAssistantModel("local/other")).rejects.toThrow("当前回复完成");
  });

  it("rejects malformed model IDs without sending or changing a draft", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    for (const modelId of ["", " local/other", "local/other\n", "x".repeat(201)])
      await expect(setLauncherAssistantModel(modelId)).rejects.toThrow("请选择可用");
    expect(invoke).not.toHaveBeenCalled();
  });

  it("accepts safe model choices and rejects accidental credential fields", async () => {
    const choice = { modelId: "local/other", label: "Other", providerLabel: "Local", isDefault: false,
      providerHealthy: true, missingApiKey: false, availability: "available" };
    const status = { assistant: { agentId: "pa", directSessionId: "s", displayName: "PA" }, settings: {
      ok: true, preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" },
      displayName: "PA", modelId: "local/other", modelChoices: [choice] } };
    const invoke = vi.fn().mockResolvedValue(status);
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantStatus()).resolves.toEqual(status);
    invoke.mockResolvedValueOnce({ ...status, settings: { ...status.settings, modelChoices: [{ ...choice, apiKey: "private" }] } });
    await expect(getLauncherAssistantStatus()).rejects.toThrow("模型列表不可用");
  });
});

describe("Launcher team run reads", () => {
  const assistant = { agentId: "pa", directSessionId: "session" };
  const row = { projectId: "project-a", requestId: "request-1", originAction: "team_run", teamId: "team-1",
    flowId: "flow-1", runId: "run-1", status: "running", revision: null, title: "", readState: "ready",
    observedAt: "2026-11-02T06:00:00+00:00", businessAcceptance: "not_evaluated" };
  const page = () => ({ schemaVersion: 1, assistant, teamRuns: [{ ...row }], offset: 0, total: 1, nextCursor: null,
    coverage: { kind: "local_associations", historyComplete: false, legacyUnrecoverable: 0, invalidRecords: 0 }, state: "ready" });
  const cursor = (offset: number, snapshot = "a".repeat(64)) => btoa(JSON.stringify({ snapshot, offset })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");

  it("reads only the fixed IPC verb and preserves native running after launch acceptance", async () => {
    const invoke = vi.fn().mockResolvedValue(page());
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantTeamRuns(assistant)).resolves.toEqual(page());
    expect(invoke).toHaveBeenCalledExactlyOnceWith({ operation: "teamRuns" });
  });

  it.each(["ready", "unknown"])("normalizes nullable optional metadata without hiding a %s native run", async readState => {
    const nativeRow = readState === "ready" ? row : { ...row, teamId: null, flowId: null, runId: null,
      status: null, observedAt: null, readState };
    const optional = { teamName: null, projectName: null, current: null, stepCount: null, attemptCount: null,
      currentAgentName: null, createdAt: null, updatedAt: null, resultSummary: null, error: null };
    const response = { ...page(), state: readState === "ready" ? "ready" : "partial", teamRuns: [{ ...nativeRow, ...optional }] };
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(response) });
    await expect(getLauncherAssistantTeamRuns(assistant)).resolves.toEqual({ ...response, teamRuns: [nativeRow] });
  });

  it.each([{ teamName: 1 }, { projectName: [] }, { currentAgentName: false }, { stepCount: -1 }, { attemptCount: 0.5 }])(
    "still rejects malformed non-null optional metadata %j", async metadata => {
      vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue({ ...page(), teamRuns: [{ ...row, ...metadata }] }) });
      await expect(getLauncherAssistantTeamRuns(assistant)).rejects.toThrow("团队运行暂不可用");
    },
  );

  it("binds pagination to the same inventory and exact offset", async () => {
    const nextCursor = cursor(1);
    const invoke = vi.fn().mockResolvedValueOnce({ ...page(), total: 2, nextCursor })
      .mockResolvedValueOnce({ ...page(), offset: 1, total: 2 });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantTeamRuns(assistant)).resolves.toMatchObject({ nextCursor });
    await expect(getLauncherAssistantTeamRuns(assistant, nextCursor)).resolves.toMatchObject({ offset: 1 });
    expect(invoke.mock.calls[1]).toEqual([{ operation: "teamRuns", cursor: nextCursor }]);
  });

  it.each([
    () => ({ ...page(), assistant: { ...assistant, directSessionId: "other" } }),
    () => ({ ...page(), teamRuns: [{ ...row, teamId: null }] }),
    () => ({ ...page(), teamRuns: [{ ...row, readState: "unknown" }] }),
    () => ({ ...page(), teamRuns: [{ ...row, businessAcceptance: "completed" }] }),
    () => ({ ...page(), teamRuns: [{ ...row, privatePrompt: "not part of DTO" }] }),
    () => ({ ...page(), total: 2 }),
    () => ({ ...page(), total: 2, nextCursor: cursor(9) }),
    () => ({ ...page(), coverage: { ...page().coverage, historyComplete: true } }),
    () => ({ ...page(), offset: 1, total: 2 }),
  ])("rejects unbound, cross-identity or inconsistent pages", async makeResult => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(makeResult()) });
    await expect(getLauncherAssistantTeamRuns(assistant)).rejects.toThrow("团队运行暂不可用");
  });

  it("retains an unknown request without turning an unavailable read into an empty list", async () => {
    const result = { ...page(), state: "partial", teamRuns: [{ ...row, teamId: null, flowId: null, runId: null,
      readState: "unknown", status: null, observedAt: null, title: {} }] };
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(result) });
    await expect(getLauncherAssistantTeamRuns(assistant)).resolves.toMatchObject({ state: "partial",
      teamRuns: [{ requestId: "request-1", readState: "unknown", title: "" }] });
  });

  it("does not send malformed cursors to the host", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantTeamRuns(assistant, "../private")).rejects.toThrow();
    await expect(getLauncherAssistantTeamRuns(assistant, cursor(-1))).rejects.toThrow();
    expect(invoke).not.toHaveBeenCalled();
  });
});

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

describe("Launcher assistant avatar", () => {
  const image = { contentType: "image/svg+xml", dataBase64: "AQI=", sha256: "a".repeat(64) };
  const response = { schemaVersion: 1, agentId: "a", image };
  it("reads a fixed private operation and never sends identity, URL or HTTP", async () => {
    const invoke = vi.fn().mockResolvedValue(response), fetch = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke }); vi.stubGlobal("fetch", fetch);
    expect((await getLauncherAssistantAvatar("a")).image?.url).toBe("data:image/svg+xml;base64,AQI=");
    expect(invoke).toHaveBeenCalledExactlyOnceWith({ operation: "assistantAvatar" });
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each([
    { ...response, agentId: "other" }, { ...response, path: "private" }, { ...response, schemaVersion: 2 },
    { ...response, image: { ...image, url: "https://example.test" } },
    { ...response, image: { ...image, contentType: "text/html" } },
    { ...response, image: { ...image, dataBase64: "AR==" } },
    { ...response, image: { ...image, sha256: "bad" } },
  ])("rejects untrusted image responses", async value => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue(value) });
    await expect(getLauncherAssistantAvatar("a")).rejects.toThrow("图片资源不可用");
  });
  it("enforces 5 MiB and accepts a cleared image", async () => {
    const encode = (length: number) => "AAAA".repeat(Math.floor(length / 3)) + (length % 3 === 1 ? "AA==" : length % 3 === 2 ? "AAA=" : "");
    const invoke = vi.fn().mockResolvedValue({ ...response, image: { ...image, dataBase64: encode(5 * 1024 * 1024) } });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    expect((await getLauncherAssistantAvatar("a")).image).toBeTruthy();
    invoke.mockResolvedValue({ ...response, image: { ...image, dataBase64: encode(5 * 1024 * 1024 + 1) } });
    await expect(getLauncherAssistantAvatar("a")).rejects.toThrow("图片资源不可用");
    invoke.mockResolvedValue({ ...response, image: null });
    expect((await getLauncherAssistantAvatar("a")).image).toBeNull();
  });
  it("supports old hosts and validates the optional capability and revision", async () => {
    const assistant = { agentId: "a", directSessionId: "s", displayName: "Assistant" };
    const invoke = vi.fn().mockResolvedValue({ assistant });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    expect((await getLauncherAssistantStatus()).assistantAvatarVersion).toBeUndefined();
    invoke.mockResolvedValue({ assistant, assistantAvatarVersion: 1, assistantAvatarRevision: null });
    expect((await getLauncherAssistantStatus()).assistantAvatarRevision).toBeNull();
    for (const invalid of [{ assistantAvatarVersion: 2 }, { assistantAvatarVersion: undefined }, { assistantAvatarRevision: "broken" }, { assistantAvatarRevision: undefined }]) {
      invoke.mockResolvedValue({ assistant, ...invalid });
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
  it("switches the head with a trimmed node id and verifies the returned session", async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ id: "s", messages: [{ id: "m1" }] })
      .mockResolvedValueOnce({ id: "other", messages: [] });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(switchLauncherAssistantHead("s", "  target-node  ")).resolves.toMatchObject({ id: "s" });
    expect(invoke.mock.calls[0]).toEqual([{ operation: "switchHead", nodeId: "target-node" }]);
    await expect(switchLauncherAssistantHead("s", "x")).rejects.toThrow("未确认版本切换所属会话");
    await expect(switchLauncherAssistantHead("s", "   ")).rejects.toThrow("版本标识无效");
    await expect(switchLauncherAssistantHead("s", "x".repeat(201))).rejects.toThrow("版本标识无效");
    // Only the two well-formed attempts reached the bridge; blank and oversized
    // node ids are refused renderer-side without any transport use.
    expect(invoke.mock.calls).toHaveLength(2);
  });
  it("regenerates with a trimmed message id and keeps the request id contract", async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ id: "s", messages: [{ id: "m1" }] })
      .mockResolvedValueOnce({ id: "other", messages: [] });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(regenerateLauncherAssistantMessage("s", " target-message ", "regen-1")).resolves.toMatchObject({ id: "s" });
    expect(invoke.mock.calls[0]).toEqual([{ operation: "regenerate", messageId: "target-message", requestId: "regen-1" }]);
    await expect(regenerateLauncherAssistantMessage("s", "target-message", "regen-1")).rejects.toThrow("未确认重新生成");
    await expect(regenerateLauncherAssistantMessage("s", "   ", "regen-1")).rejects.toThrow("消息标识无效");
    await expect(regenerateLauncherAssistantMessage("s", "target-message", "bad id")).rejects.toThrow("请求标识无效");
    // Only the two well-formed attempts reached the bridge; malformed ids are
    // refused renderer-side without any transport use.
    expect(invoke.mock.calls).toHaveLength(2);
  });
  it("sends bounded reference chips on the same closed send verb", async () => {
    const invoke = vi.fn().mockResolvedValue({ accepted: true, turnId: "turn-refs" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    const reference = { kind: "message", referenceId: "message:m1", sourceSessionId: "s", sourceMessageId: "m1", quote: "text" };
    await expect(sendLauncherAssistantMessage("see this", "send-refs", [], [reference])).resolves.toEqual({ turnId: "turn-refs" });
    expect(invoke.mock.calls[0]).toEqual([{ operation: "send", message: "see this", requestId: "send-refs", references: [reference] }]);
    await expect(sendLauncherAssistantMessage("", "send-refs", [], [{ kind: "" } as typeof reference])).rejects.toThrow("消息或请求标识无效");
    await expect(sendLauncherAssistantMessage("see this", "send-refs", [], Array(9).fill(reference))).rejects.toThrow("消息或请求标识无效");
    expect(invoke.mock.calls).toHaveLength(1);
  });
  it("steers only with non-empty guidance content and a fixed mode", async () => {
    const invoke = vi.fn().mockResolvedValue({ id: "s" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(guideLauncherAssistantTurn("s", " hold on ", "safe")).resolves.toMatchObject({ id: "s" });
    expect(invoke.mock.calls[0]).toEqual([{ operation: "guidance", content: " hold on ", mode: "safe" }]);
    await expect(guideLauncherAssistantTurn("s", "   ", "interrupt")).rejects.toThrow("引导内容无效");
    await expect(guideLauncherAssistantTurn("s", "hold on", "unsafe")).rejects.toThrow("引导模式无效");
    expect(invoke.mock.calls).toHaveLength(1);
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

  it("reads optional bounded task titles while accepting legacy title-less receipts", async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ dispatches: [{ dispatchId: "d", title: "整理资料" }] })
      .mockResolvedValueOnce({ dispatches: [{ dispatchId: "legacy" }] });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(getLauncherAssistantDispatches()).resolves.toEqual([{ dispatchId: "d", title: "整理资料" }]);
    await expect(getLauncherAssistantDispatches()).resolves.toEqual([{ dispatchId: "legacy" }]);
    expect(invoke.mock.calls).toEqual([[{ operation: "dispatches" }], [{ operation: "dispatches" }]]);
  });

  it.each([null, {}, "x".repeat(161)])("retains a task when optional title metadata is invalid", async title => {
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn().mockResolvedValue({ dispatches: [{ dispatchId: "d", title }] }) });
    await expect(getLauncherAssistantDispatches()).resolves.toEqual([{ dispatchId: "d" }]);
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

describe("Launcher session event subscription", () => {
  it("returns null without throwing when the bridge or its push verb is absent", () => {
    vi.stubGlobal("vibelutionLauncherAssistant", undefined);
    expect(subscribeLauncherAssistantSessionEvent(() => {})).toBeNull();
    // An older shell exposes only `invoke`: capability detection, never a throw.
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn() });
    expect(subscribeLauncherAssistantSessionEvent(() => {})).toBeNull();
    expect(subscribeLauncherAssistantSessionEvent(() => {}, null)).toBeNull();
    expect(subscribeLauncherAssistantSessionEvent(() => {}, {})).toBeNull();
    expect(subscribeLauncherAssistantSessionEvent(() => {}, { vibelutionLauncherAssistant: { onSessionEvent: "not callable" } })).toBeNull();
  });

  it("subscribes through the preload verb, forwards only well-formed frames and hands back its unsubscribe", () => {
    const unsubscribe = vi.fn();
    let handler: ((event: unknown) => void) | undefined;
    const onSessionEvent = vi.fn((next: (event: unknown) => void) => { handler = next; return unsubscribe; });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke: vi.fn(), onSessionEvent });
    const listener = vi.fn();
    const stop = subscribeLauncherAssistantSessionEvent(listener);
    expect(stop).toBeTypeOf("function");
    expect(onSessionEvent).toHaveBeenCalledTimes(1);
    const snapshot = { type: "session_detail", sessionId: "s", ledgerSeq: 7, at: 1 };
    const heartbeat = { type: "heartbeat", sessionId: "s", at: 2 };
    handler?.(snapshot);
    handler?.(heartbeat);
    for (const malformed of [null, undefined, "text", 3, { type: 1, sessionId: "s", at: 3 }, { type: "session_detail", at: 4 }, { sessionId: "s", at: 5 }]) handler?.(malformed);
    expect(listener.mock.calls).toEqual([[snapshot], [heartbeat]]);
    expect(unsubscribe).not.toHaveBeenCalled();
    stop?.();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });

  it("treats a throwing subscribe as no channel and never lets teardown throw", () => {
    vi.stubGlobal("vibelutionLauncherAssistant", { onSessionEvent: () => { throw new Error("bridge gone"); } });
    expect(subscribeLauncherAssistantSessionEvent(() => {})).toBeNull();
    vi.stubGlobal("vibelutionLauncherAssistant", { onSessionEvent: () => undefined });
    const noUnsubscribe = subscribeLauncherAssistantSessionEvent(() => {});
    expect(noUnsubscribe).toBeTypeOf("function");
    expect(() => noUnsubscribe?.()).not.toThrow();
    const unsubscribe = vi.fn(() => { throw new Error("channel already closed"); });
    vi.stubGlobal("vibelutionLauncherAssistant", { onSessionEvent: () => unsubscribe });
    const throwingUnsubscribe = subscribeLauncherAssistantSessionEvent(() => {});
    expect(() => throwingUnsubscribe?.()).not.toThrow();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });
});

describe("Launcher user secret staging", () => {
  it("sends value plus optional label on the closed verb, never secretKind", async () => {
    const invoke = vi.fn().mockResolvedValue({ attachmentId: "sec_abc123", kind: "user_secret" });
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    await expect(uploadLauncherUserSecret("sk-live-value", "中转站密钥")).resolves
      .toEqual({ attachmentId: "sec_abc123", kind: "user_secret" });
    expect(invoke).toHaveBeenLastCalledWith({ operation: "upload_attachment", kind: "user_secret",
      value: "sk-live-value", label: "中转站密钥" });
    await expect(uploadLauncherUserSecret("sk-live-value")).resolves
      .toEqual({ attachmentId: "sec_abc123", kind: "user_secret" });
    expect(invoke).toHaveBeenLastCalledWith({ operation: "upload_attachment", kind: "user_secret", value: "sk-live-value" });
    await expect(uploadLauncherUserSecret("", "label")).rejects.toThrow("请粘贴隐私内容后再提交。");
    await expect(uploadLauncherUserSecret("value", "x".repeat(161))).rejects.toThrow("显示名无效。");
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it("accepts exactly 2-key or 3-key confirmations and rejects every other shape", async () => {
    const invoke = vi.fn();
    vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
    for (const confirmed of [
      { attachmentId: "sec_abc123", kind: "user_secret" },
      { attachmentId: "sec_abc123", kind: "user_secret", label: "中转站密钥" },
    ]) {
      invoke.mockResolvedValueOnce(confirmed);
      await expect(uploadLauncherUserSecret("sk-live-value", "中转站密钥")).resolves
        .toEqual({ attachmentId: "sec_abc123", kind: "user_secret" });
    }
    for (const invalid of [
      null,
      { attachmentId: "sec_abc123" },
      { attachmentId: "sec_abc123", kind: "user_secret", extra: 1 },
      { attachmentId: "sec_abc123", kind: "user_secret", label: 7 },
      { attachmentId: "sec_abc123", kind: "user_secret", label: "x".repeat(161) },
      { attachmentId: "user-image-1.png", kind: "user_secret" },
      { attachmentId: "sec_abc123", kind: "user_image" },
    ]) {
      invoke.mockResolvedValueOnce(invalid);
      await expect(uploadLauncherUserSecret("sk-live-value")).rejects.toThrow("Launcher 未确认隐私附件暂存。");
    }
    expect(invoke).toHaveBeenCalledTimes(9);
  });
});
