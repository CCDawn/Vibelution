import { afterEach, describe, expect, it, vi } from "vitest";
import { ASSISTANT_BRIDGE_OPERATIONS, invokeAssistant, LAUNCHER_ASSISTANT_URL } from "../src/assistant/assistantBridge.js";
import type { AssistantHostRequest } from "../src/assistant/assistantHost.js";

/**
 * Every member of AssistantHostRequest["operation"] (src/assistant/
 * assistantHost.ts). The const's type pins each entry to the host union, and
 * hostRequestListIsExhaustive below fails to compile when the union gains a
 * member missing from this list, so a new host verb cannot land silently.
 */
const HOST_REQUEST_OPERATIONS: readonly AssistantHostRequest["operation"][] = [
  "previewTaskCleanup", "executeTaskCleanup", "teamRuns", "setModel", "setManagementPermissionPreset", "budgetParameters", "setBudgetParameters", "usageSummary",
  "detail", "status", "dispatches", "config", "approvals", "assistantAvatar",
  "resolveApproval", "previewDispatchApproval", "declineDispatchApproval", "decideDispatchApproval",
  "send", "uploadAttachment", "upload_attachment", "readAttachment", "stop", "updateQueuedTurn", "removeQueuedTurn", "sendNowQueuedTurn", "continue", "switchHead", "regenerate", "guidance",
  "curation", "curate", "operatorAsset",
  "computerState", "computerWindows", "computerGrant", "computerControl", "computerConfirm",
];

function setup() {
  const mainFrame = { url: LAUNCHER_ASSISTANT_URL };
  const contents = { mainFrame, isDestroyed: () => false };
  const owner = { contents, host: { start: vi.fn(async () => ({})), request: vi.fn(async (_payload: unknown) => ({ accepted: true })) },
    hide: vi.fn(), setExpanded: vi.fn((expanded: boolean) => ({ expanded })), openLauncher: vi.fn(async () => ({ opened: true })) };
  return { owner, event: { sender: contents, senderFrame: mainFrame } };
}

describe("Launcher assistant private bridge", () => {
  afterEach(() => { vi.useRealTimers(); });

  it("admits only closed queue mutations from the owned frame before starting the host", async () => {
    const { owner, event } = setup();
    const requests = [
      { operation: "updateQueuedTurn", sessionId: "s", queuedTurnId: "queued-one", content: "edited", position: 1, status: "paused" },
      { operation: "removeQueuedTurn", sessionId: "s", queuedTurnId: "queued-one" },
      { operation: "sendNowQueuedTurn", sessionId: "s", queuedTurnId: "queued-one", expectedTurnId: "running-turn" },
    ] as const;
    for (const request of requests) {
      await expect(invokeAssistant({ ...event, sender: {} }, request, owner)).rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
      for (const fields of [{ sessionId: "s\n" }, { queuedTurnId: "../foreign" }, { queuedTurnId: "q".repeat(161) },
        { agentId: "foreign" }, { url: "http://example.test" }])
        await expect(invokeAssistant(event, { ...request, ...fields }, owner)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    }
    for (const fields of [{ content: null }, { content: "x".repeat(64001) }, { position: true }, { position: 0 },
      { position: 1.5 }, { status: "starting" }, { status: undefined }])
      await expect(invokeAssistant(event, { ...requests[0], ...fields }, owner)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    for (const expectedTurnId of [undefined, null, "", "turn\n", "../foreign", "t".repeat(161)])
      await expect(invokeAssistant(event, { ...requests[2], expectedTurnId }, owner)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(owner.host.start).not.toHaveBeenCalled();
    expect(owner.host.request).not.toHaveBeenCalled();
    for (const request of requests) await invokeAssistant(event, request, owner);
    expect(owner.host.request.mock.calls.map(([request]) => request)).toEqual(requests);
  });

  it.each(["updateQueuedTurn", "removeQueuedTurn", "sendNowQueuedTurn"])("waits for full host start for %s writes", async operation => {
    vi.useFakeTimers();
    const { owner, event } = setup();
    let release!: (value: unknown) => void;
    owner.host.start.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    const request = { operation, sessionId: "s", queuedTurnId: "queued-one" };
    const pending = invokeAssistant(event, request, owner);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(owner.host.request).not.toHaveBeenCalled();
    release({});
    await pending;
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith(request);
  });

  it("rejects usage identity, scope and path injection before host start", async () => {
    const { owner, event } = setup();
    for (const field of ["sessionId", "agentId", "scope", "projectRoot", "ledgerPath"])
      await expect(invokeAssistant(event, { operation: "usageSummary", [field]: "foreign" }, owner))
        .rejects.toThrow("ASSISTANT_USAGE_INVALID");
    expect(owner.host.start).not.toHaveBeenCalled();
    await expect(invokeAssistant({ ...event, sender: {} }, { operation: "usageSummary" }, owner))
      .rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
    await invokeAssistant(event, { operation: "usageSummary" }, owner);
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith({ operation: "usageSummary" });
  });

  it("admits only a closed management-permission CAS request before starting the host", async () => {
    const { owner, event } = setup();
    const request = { operation: "setManagementPermissionPreset", preset: "full_access", expectedRevision: 0 };
    for (const payload of [
      { ...request, preset: "custom" }, { ...request, preset: true }, { ...request, expectedRevision: true },
      { ...request, expectedRevision: -1 }, { ...request, expectedRevision: 0.5 }, { ...request, expectedRevision: Number.MAX_SAFE_INTEGER + 1 },
      { ...request, projectId: "foreign" }, { ...request, agentId: "foreign" }, { ...request, expectedRevision: undefined },
    ]) await expect(invokeAssistant(event, payload, owner)).rejects.toThrow("ASSISTANT_PERMISSION_INVALID");
    expect(owner.host.start).not.toHaveBeenCalled();
    await expect(invokeAssistant({ ...event, sender: {} }, request, owner)).rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
    await invokeAssistant(event, request, owner);
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith(request);
    owner.host.request.mockRejectedValueOnce(new Error("ASSISTANT_PERMISSION_CONFLICT"));
    await expect(invokeAssistant(event, request, owner)).rejects.toThrow("ASSISTANT_PERMISSION_CONFLICT");
    expect(owner.host.request).toHaveBeenCalledTimes(2);
  });

  it("admits a closed model change from the float and rejects identity injection before host start", async () => {
    const { owner, event } = setup();
    for (const payload of [{ operation: "setModel", modelId: "" }, { operation: "setModel", modelId: "local/model\n" },
      { operation: "setModel", modelId: "local/model", agentId: "foreign" },
      { operation: "setModel", modelId: "local/model", directSessionId: "foreign" }])
      await expect(invokeAssistant(event, payload, owner)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    expect(owner.host.start).not.toHaveBeenCalled();
    await expect(invokeAssistant(event, { operation: "setModel", modelId: "local/model" }, owner)).resolves.toEqual({ accepted: true });
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith({ operation: "setModel", modelId: "local/model" });
  });
  it("admits only the fixed assistant avatar operation from the owned frame", async () => {
    const { owner, event } = setup();
    await expect(invokeAssistant({ ...event, sender: {} }, { operation: "assistantAvatar" }, owner)).rejects.toThrow("SENDER_FORBIDDEN");
    for (const extra of [{ path: "private" }, { url: "http://example.test" }, { agentId: "other" }]) {
      await expect(invokeAssistant(event, { operation: "assistantAvatar", ...extra }, owner)).rejects.toThrow("REQUEST_INVALID");
    }
    expect(owner.host.start).not.toHaveBeenCalled();
    await invokeAssistant(event, { operation: "assistantAvatar" }, owner);
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith({ operation: "assistantAvatar" });
  });
  it("opens the existing Launcher through a closed human action without starting a model host", async () => {
    const { owner, event } = setup();
    await expect(invokeAssistant(event, { operation: "openLauncher" }, owner)).resolves.toEqual({ opened: true });
    expect(owner.openLauncher).toHaveBeenCalledExactlyOnceWith();
    expect(owner.host.start).not.toHaveBeenCalled();
    expect(owner.host.request).not.toHaveBeenCalled();
    await expect(invokeAssistant(event, { operation: "openLauncher", root: "untrusted" }, owner)).rejects.toThrow("REQUEST_INVALID");
    owner.openLauncher.mockRejectedValueOnce(new Error("private path"));
    await expect(invokeAssistant(event, { operation: "openLauncher" }, owner)).rejects.toThrow("ASSISTANT_LAUNCHER_UNAVAILABLE");
  });
  it.each(["http://127.0.0.1:8000/launcher-assistant", "vibelution-launcher://launcher/launcher",
    LAUNCHER_ASSISTANT_URL + "?token=untrusted", LAUNCHER_ASSISTANT_URL + "/nested"])("denies another URL %s", async url => {
    const { owner, event } = setup();
    event.senderFrame.url = url;
    await expect(invokeAssistant(event, { operation: "status" }, owner)).rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
    expect(owner.host.start).not.toHaveBeenCalled();
  });
  it("denies another window and same-origin subframe", async () => {
    const { owner, event } = setup();
    await expect(invokeAssistant({ ...event, sender: {} }, { operation: "status" }, owner)).rejects.toThrow("SENDER_FORBIDDEN");
    await expect(invokeAssistant({ ...event, senderFrame: { ...event.senderFrame } }, { operation: "status" }, owner)).rejects.toThrow("SENDER_FORBIDDEN");
  });
  it("routes attachment operations only from the owned assistant frame", async () => {
    const { owner, event } = setup();
    const upload = { operation: "uploadAttachment", filename: "note.txt", contentType: "text/plain", dataBase64: "Zml4dHVyZQ==" };
    await expect(invokeAssistant({ ...event, sender: {} }, upload, owner)).rejects.toThrow("SENDER_FORBIDDEN");
    await invokeAssistant(event, upload, owner);
    await invokeAssistant(event, { operation: "readAttachment", artifactId: "file-1" }, owner);
    expect(owner.host.request).toHaveBeenCalledTimes(2);
  });
  it("accepts fixed computer verbs only from the owned top-level assistant frame", async () => {
    const { owner, event } = setup();
    Object.assign(owner.host, { snapshot: () => ({ state: "ready" }) });
    for (const operation of ["computerState", "computerWindows", "computerGrant", "computerControl", "computerConfirm"]) {
      await expect(invokeAssistant({ ...event, sender: {} }, { operation }, owner)).rejects.toThrow("SENDER_FORBIDDEN");
      await invokeAssistant(event, { operation }, owner);
    }
    expect(owner.host.request).toHaveBeenCalledTimes(5);
    expect(owner.host.start).toHaveBeenCalledTimes(3);
    await expect(invokeAssistant(event, { operation: "computerExecute" }, owner)).rejects.toThrow("REQUEST_INVALID");
  });
  it("keeps the bridge verb whitelist in lockstep with the host operation union", () => {
    // Compile-time guard: fails to build when HOST_REQUEST_OPERATIONS no
    // longer covers AssistantHostRequest, so a new host verb cannot be added
    // without extending this list and re-checking the bridge whitelist.
    const hostRequestListIsExhaustive: Exclude<AssistantHostRequest["operation"], typeof HOST_REQUEST_OPERATIONS[number]> extends never ? true : never = true;
    expect(hostRequestListIsExhaustive).toBe(true);
    for (const operation of HOST_REQUEST_OPERATIONS) expect(ASSISTANT_BRIDGE_OPERATIONS).toContain(operation);
  });
  it("forwards the regenerate, switchHead and guidance writes to the host unchanged", async () => {
    const { owner, event } = setup();
    const payloads = [
      { operation: "regenerate", messageId: "message-1", requestId: "request-1" },
      { operation: "switchHead", nodeId: "node-1" },
      { operation: "guidance", content: "focus the summary", mode: "safe" },
    ] as const;
    for (const payload of payloads) await expect(invokeAssistant(event, payload, owner)).resolves.toEqual({ accepted: true });
    expect(owner.host.start).toHaveBeenCalledTimes(3);
    expect(owner.host.request).toHaveBeenCalledTimes(3);
    expect(owner.host.request).toHaveBeenNthCalledWith(1, payloads[0]);
    expect(owner.host.request).toHaveBeenNthCalledWith(2, payloads[1]);
    expect(owner.host.request).toHaveBeenNthCalledWith(3, payloads[2]);
  });
  it("rejects the retired panel operations before starting or reaching the host", async () => {
    const { owner, event } = setup();
    for (const operation of ["panelSettings", "panelSettingsUpdate", "panelModelUpdate", "panelDialogue", "panelDialogueUpdate",
      "panelProposals", "panelProposalAccept", "panelProposalReject", "panelAffairs", "panelAffairAdd",
      "panelAffairComplete", "panelAffairCancel", "panelAffairReopen", "panelAffairDue"]) {
      await expect(invokeAssistant(event, { operation }, owner)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    }
    expect(owner.host.start).not.toHaveBeenCalled();
    expect(owner.host.request).not.toHaveBeenCalled();
  });
  it("hides or resizes without changing native owner lifecycle", async () => {
    const { owner, event } = setup();
    expect(await invokeAssistant(event, { operation: "hide" }, owner)).toEqual({ hidden: true });
    expect(await invokeAssistant(event, { operation: "setExpanded", expanded: true }, owner)).toEqual({ expanded: true });
    expect(owner.host.start).not.toHaveBeenCalled();
    await expect(invokeAssistant(event, { operation: "hide", path: "private" }, owner)).rejects.toThrow("REQUEST_INVALID");
    await expect(invokeAssistant(event, { operation: "shutdown" }, owner)).rejects.toThrow("REQUEST_INVALID");
  });
  it("starts for a new invocation, propagates one failed write, and never replays it", async () => {
    const { owner, event } = setup();
    owner.host.request.mockRejectedValueOnce(new Error("raw path or credential"));
    const payload = { operation: "send", message: "hello", requestId: "stable" };
    await expect(invokeAssistant(event, payload, owner)).rejects.toThrow("ASSISTANT_REQUEST_FAILED");
    expect(owner.host.start).toHaveBeenCalledTimes(1);
    expect(owner.host.request).toHaveBeenCalledTimes(1);
    expect(owner.host.request).toHaveBeenCalledWith(payload);
    await invokeAssistant(event, { operation: "status" }, owner);
    expect(owner.host.request).toHaveBeenCalledTimes(2);
  });
  it("passes the native attachment-not-found code through for the renderer's missing-attachment verdict", async () => {
    const { owner, event } = setup();
    owner.host.request.mockRejectedValueOnce(new Error("ATTACHMENT_NOT_FOUND"));
    await expect(invokeAssistant(event, { operation: "readAttachment", artifactId: "file-1" }, owner))
      .rejects.toThrow("ATTACHMENT_NOT_FOUND");
  });
  it.each(["status", "budgetParameters", "usageSummary"])("bounds %s read wait on host start", async operation => {
    vi.useFakeTimers();
    const { owner, event } = setup();
    let releaseStart!: (value: unknown) => void;
    owner.host.start.mockImplementation(() => new Promise(resolve => { releaseStart = resolve; }));
    owner.host.request.mockRejectedValue(new Error("ASSISTANT_NOT_READY"));
    let failure = "";
    const read = invokeAssistant(event, { operation }, owner)
      .catch((error: unknown) => { failure = error instanceof Error ? error.message : ""; });
    await vi.advanceTimersByTimeAsync(1_999);
    expect(failure).toBe("");
    expect(owner.host.request).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await read;
    expect(failure).toBe("ASSISTANT_NOT_READY");
    // The recovery start itself was still triggered and stays in flight.
    expect(owner.host.start).toHaveBeenCalledTimes(1);
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith({ operation });
    releaseStart({});
    await Promise.resolve();
  });
  it("keeps a write invoke waiting on the full host start", async () => {
    vi.useFakeTimers();
    const { owner, event } = setup();
    let releaseStart!: (value: unknown) => void;
    owner.host.start.mockImplementation(() => new Promise(resolve => { releaseStart = resolve; }));
    let settled = false;
    const write = invokeAssistant(event, { operation: "send", message: "m", requestId: "r" }, owner)
      .then(() => { settled = true; }, () => { settled = true; });
    await vi.advanceTimersByTimeAsync(120_000);
    expect(settled).toBe(false);
    expect(owner.host.request).not.toHaveBeenCalled();
    releaseStart({});
    await write;
    expect(settled).toBe(true);
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith({ operation: "send", message: "m", requestId: "r" });
  });
});

describe("Workbench main window sender admission", () => {
  function workbenchSenderSetup() {
    const mainFrame = { url: LAUNCHER_ASSISTANT_URL };
    const contents = { mainFrame, isDestroyed: () => false };
    const workbenchFrame = { url: "http://127.0.0.1:8642/launcher-assistant" };
    const workbenchContents = { mainFrame: workbenchFrame, isDestroyed: () => false };
    const owner = { contents, host: { start: vi.fn(async () => ({})), request: vi.fn(async (_payload: unknown) => ({ accepted: true })) },
      hide: vi.fn(), setExpanded: vi.fn((expanded: boolean) => ({ expanded })),
      // Mirrors the main-held WeakSet registry: exact identity, nothing else.
      isWorkbenchSender: (sender: unknown) => sender === workbenchContents };
    return { owner, workbenchContents, event: { sender: workbenchContents as unknown, senderFrame: workbenchFrame as { url: string } | null } };
  }

  it("admits the registered workbench main webContents by identity without URL matching", async () => {
    const { owner, event } = workbenchSenderSetup();
    await expect(invokeAssistant(event, { operation: "status" }, owner)).resolves.toEqual({ accepted: true });
    expect(owner.host.start).toHaveBeenCalledTimes(1);
    await expect(invokeAssistant(event, { operation: "hide" }, owner)).resolves.toEqual({ hidden: true });
    expect(owner.hide).toHaveBeenCalledExactlyOnceWith();
    await invokeAssistant(event, { operation: "setModel", modelId: "local/model" }, owner);
    expect(owner.host.request).toHaveBeenLastCalledWith({ operation: "setModel", modelId: "local/model" });
  });

  it.each<[string, (s: ReturnType<typeof workbenchSenderSetup>) => void]>([
    ["an unregistered sender identity", s => { s.event.sender = { mainFrame: s.event.senderFrame }; }],
    ["a subframe of the workbench window", s => { s.event.senderFrame = { url: (s.event.senderFrame as { url: string }).url }; }],
    ["a missing sender frame", s => { s.event.senderFrame = null; }],
    ["a gate that refuses the sender", s => { s.owner.isWorkbenchSender = () => false; }],
    ["a non-object sender", s => { s.event.sender = null; }]
  ])("fails closed for %s", async (_label, breakSetup) => {
    const state = workbenchSenderSetup();
    breakSetup(state);
    await expect(invokeAssistant(state.event, { operation: "status" }, state.owner)).rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
    expect(state.owner.host.request).not.toHaveBeenCalled();
    expect(state.owner.host.start).not.toHaveBeenCalled();
  });

  it("keeps the pet float assertion pet-only when no workbench gate is provided", async () => {
    const mainFrame = { url: LAUNCHER_ASSISTANT_URL };
    const contents = { mainFrame, isDestroyed: () => false };
    const owner = { contents, host: { start: vi.fn(async () => ({})), request: vi.fn(async () => ({})) },
      hide: vi.fn(), setExpanded: vi.fn() };
    const workbenchFrame = { url: "http://127.0.0.1:8642/launcher-assistant" };
    const workbenchContents = { mainFrame: workbenchFrame, isDestroyed: () => false };
    await expect(invokeAssistant({ sender: workbenchContents, senderFrame: workbenchFrame }, { operation: "status" }, owner))
      .rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
    expect(owner.host.request).not.toHaveBeenCalled();
    await expect(invokeAssistant({ sender: contents, senderFrame: mainFrame }, { operation: "status" }, owner))
      .resolves.toEqual({});
  });
});

describe("Launcher control window sender admission", () => {
  function launcherControlSetup() {
    const mainFrame = { url: LAUNCHER_ASSISTANT_URL };
    const contents = { mainFrame, isDestroyed: () => false };
    const controlFrame = { url: "vibelution-launcher://launcher/launcher" };
    const controlContents = { mainFrame: controlFrame, isDestroyed: () => false };
    const owner = { contents, host: { start: vi.fn(async () => ({})), request: vi.fn(async (_payload: unknown) => ({ accepted: true })) },
      hide: vi.fn(), setExpanded: vi.fn((expanded: boolean) => ({ expanded })),
      // Mirrors the main-held WeakSet registry: exact identity, nothing else.
      isLauncherControlSender: (sender: unknown) => sender === controlContents };
    return { owner, controlContents, event: { sender: controlContents as unknown, senderFrame: controlFrame as { url: string } | null } };
  }

  it("admits the registered launcher control webContents by identity without URL matching", async () => {
    const { owner, event } = launcherControlSetup();
    await expect(invokeAssistant(event, { operation: "status" }, owner)).resolves.toEqual({ accepted: true });
    expect(owner.host.start).toHaveBeenCalledTimes(1);
    await expect(invokeAssistant(event, { operation: "hide" }, owner)).resolves.toEqual({ hidden: true });
    expect(owner.hide).toHaveBeenCalledExactlyOnceWith();
  });

  it("reaches the host with no float contents once the pet float is gone", async () => {
    // Host-direct registration shape: the owner carries no float webContents,
    // so a closed float cannot turn a full-size session into ASSISTANT_NOT_READY.
    const { owner, event } = launcherControlSetup();
    delete (owner as { contents?: unknown }).contents;
    await expect(invokeAssistant(event, { operation: "status" }, owner)).resolves.toEqual({ accepted: true });
    expect(owner.host.request).toHaveBeenCalledExactlyOnceWith({ operation: "status" });
    await expect(invokeAssistant(event, { operation: "hide" }, owner)).resolves.toEqual({ hidden: true });
  });

  it.each<[string, (s: ReturnType<typeof launcherControlSetup>) => void]>([
    ["an unregistered sender identity", s => { s.event.sender = { mainFrame: s.event.senderFrame }; }],
    ["a subframe of the launcher control window", s => { s.event.senderFrame = { url: (s.event.senderFrame as { url: string }).url }; }],
    ["a missing sender frame", s => { s.event.senderFrame = null; }],
    ["a gate that refuses the sender", s => { s.owner.isLauncherControlSender = () => false; }],
    ["a gate that throws", s => { s.owner.isLauncherControlSender = () => { throw new Error("gate exploded"); }; }],
    ["a missing launcher gate", s => { delete (s.owner as { isLauncherControlSender?: unknown }).isLauncherControlSender; }],
    ["a non-object sender", s => { s.event.sender = null; }]
  ])("fails closed for %s", async (_label, breakSetup) => {
    const state = launcherControlSetup();
    breakSetup(state);
    await expect(invokeAssistant(state.event, { operation: "status" }, state.owner)).rejects.toThrow("ASSISTANT_SENDER_FORBIDDEN");
    expect(state.owner.host.request).not.toHaveBeenCalled();
    expect(state.owner.host.start).not.toHaveBeenCalled();
  });
});
