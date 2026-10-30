import { describe, expect, it, vi } from "vitest";
import { invokeAssistant, LAUNCHER_ASSISTANT_URL } from "../src/assistant/assistantBridge.js";

function setup() {
  const mainFrame = { url: LAUNCHER_ASSISTANT_URL };
  const contents = { mainFrame, isDestroyed: () => false };
  const owner = { contents, host: { start: vi.fn(async () => ({})), request: vi.fn(async (_payload: unknown) => ({ accepted: true })) },
    hide: vi.fn(), setExpanded: vi.fn((expanded: boolean) => ({ expanded })), openLauncher: vi.fn(async () => ({ opened: true })) };
  return { owner, event: { sender: contents, senderFrame: mainFrame } };
}

describe("Launcher assistant private bridge", () => {
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
