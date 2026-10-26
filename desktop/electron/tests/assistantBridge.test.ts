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
