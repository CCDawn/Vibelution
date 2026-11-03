import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getLauncherAssistantDetail, getLauncherAssistantDispatches, getLauncherAssistantStatus, getLauncherAssistantTeamRuns,
  hideLauncherAssistant, launcherAssistantBridge, launcherConversationApi,
  sendLauncherAssistantMessage, setLauncherAssistantExpanded, setLauncherAssistantModel,
  getLauncherAssistantApprovals, resolveLauncherAssistantApproval,
  previewLauncherDispatchApproval, decideLauncherDispatchApproval, declineLauncherDispatchSummary,
  stopLauncherAssistantTurn, continueLauncherAssistantTurn,
  getLauncherOperatorAsset, getLauncherAssistantAvatar, openLauncherFromAssistant,
  subscribeLauncherAssistantSessionEvent,
  setLauncherManagementPermissionPreset,
} from "./launcherAssistant";
import type { SessionToolApprovalRequest } from "./types";

afterEach(() => vi.unstubAllGlobals());

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
