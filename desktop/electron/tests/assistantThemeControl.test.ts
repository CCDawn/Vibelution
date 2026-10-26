import { afterEach, describe, expect, it, vi } from "vitest";
import { LAUNCHER_ASSISTANT_URL } from "../src/assistant/assistantBridge.js";
import { AssistantThemeControl } from "../src/assistant/assistantThemeControl.js";
import { createAssistantThemePreload } from "../src/assistant/assistantThemePreload.js";
import { AssistantWindow } from "../src/assistant/assistantWindow.js";
import { createPetWindow } from "../src/windows/petWindow.js";
import { dialog } from "electron";

vi.mock("electron", () => ({ dialog: { showOpenDialog: vi.fn() }, screen: {} }));
vi.mock("../src/windows/petWindow.js", () => ({ createPetWindow: vi.fn() }));

const id = (value = 1) => value.toString(16).padStart(32, "0");
function setup() {
  const mainFrame = { url: LAUNCHER_ASSISTANT_URL };
  const contents = { mainFrame, isDestroyed: vi.fn(() => false), getURL: () => mainFrame.url, send: vi.fn() };
  const control = new AssistantThemeControl();
  const event = { sender: contents, senderFrame: mainFrame };
  return { control, contents, event };
}
afterEach(() => vi.useRealTimers());

describe("owned Launcher theme commands", () => {
  it("bounds recent tombstones and permits collection after their broker lifetime", async () => {
    vi.useFakeTimers();
    const clock = vi.spyOn(performance,"now").mockReturnValue(0);
    const {control,contents,event}=setup();
    const first=control.request(contents,{deliveryId:id(),operation:"read"});
    control.acceptResult(event,{deliveryId:id(),operation:"read",code:"read",theme:"light"});
    await first;
    expect(await control.request(contents,{deliveryId:id(),operation:"read"})).toMatchObject({code:"unavailable"});
    clock.mockReturnValue(60001);
    const fresh=control.request(contents,{deliveryId:id(),operation:"read"});
    control.acceptResult(event,{deliveryId:id(),operation:"read",code:"read",theme:"dark"});
    expect((await fresh).theme).toBe("dark");clock.mockRestore();
  });

  it("reads and applies only an observed matching theme through fixed IPC", async () => {
    const { control, contents, event } = setup();
    const read = control.request(contents, { deliveryId: id(), operation: "read" });
    expect(contents.send).toHaveBeenCalledWith("vibelution:assistant-theme-command", { deliveryId: id(), operation: "read" });
    expect(control.acceptResult(event, { deliveryId: id(), operation: "read", code: "read", theme: "light" })).toBe(true);
    expect(await read).toEqual({ schemaVersion: 1, operation: "read", code: "read", theme: "light" });
    for (const [index, theme] of ["dark", "light"].entries()) {
      const pending = control.request(contents, { deliveryId: id(index + 2), operation: "set", theme: theme as "dark" | "light" });
      control.acceptResult(event, { deliveryId: id(index + 2), operation: "set", code: "applied", theme });
      expect(await pending).toEqual({ schemaVersion: 1, operation: "set", code: "applied", theme });
    }
  });

  it("rejects foreign frames, malformed data, accessors and symbols without reading them", async () => {
    const { control, contents, event } = setup();
    const pending = control.request(contents, { deliveryId: id(), operation: "read" });
    const valid = { deliveryId: id(), operation: "read", code: "read", theme: "dark" };
    expect(control.acceptResult({ ...event, sender: {} }, valid)).toBe(false);
    expect(control.acceptResult({ ...event, senderFrame: { url: LAUNCHER_ASSISTANT_URL } }, valid)).toBe(false);
    const getter = vi.fn(() => "dark");
    for (const payload of [{ ...valid, extra: true }, { ...valid, theme: "system" }, { ...valid, [Symbol()]: true },
      Object.defineProperty({ ...valid }, "theme", { get: getter }), { ...valid, code: "applied" }]) {
      expect(control.acceptResult(event, payload)).toBe(false);
    }
    expect(getter).not.toHaveBeenCalled();
    event.senderFrame.url += "?foreign";
    expect(control.acceptResult(event, valid)).toBe(false);
    event.senderFrame.url = LAUNCHER_ASSISTANT_URL;
    expect(control.acceptResult(event, valid)).toBe(true);
    expect((await pending).theme).toBe("dark");
  });

  it("fails closed on wrong observed theme and persistence failure", async () => {
    const { control, contents, event } = setup();
    const wrong = control.request(contents, { deliveryId: id(), operation: "set", theme: "dark" });
    expect(control.acceptResult(event, { deliveryId: id(), operation: "set", code: "applied", theme: "light" })).toBe(true);
    expect(await wrong).toEqual({ schemaVersion: 1, operation: "set", code: "unavailable" });
    const failed = control.request(contents, { deliveryId: id(2), operation: "set", theme: "dark" });
    control.acceptResult(event, { deliveryId: id(2), operation: "set", code: "persistence_failed" });
    expect(await failed).toEqual({ schemaVersion: 1, operation: "set", code: "persistence_failed" });
  });

  it("bounds pending commands and times out without allowing a stale delivery to be reused", async () => {
    vi.useFakeTimers();
    const { control, contents, event } = setup();
    const pending = [1, 2, 3, 4].map(value => control.request(contents, { deliveryId: id(value), operation: "read" }));
    expect(await control.request(contents, { deliveryId: id(5), operation: "read" })).toMatchObject({ code: "unavailable" });
    expect(contents.send).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(3_000);
    expect((await Promise.all(pending)).every(result => result.code === "unavailable")).toBe(true);
    expect(await control.request(contents, { deliveryId: id(), operation: "read" })).toMatchObject({ code: "unavailable" });
    expect(control.acceptResult(event, { deliveryId: id(), operation: "read", code: "read", theme: "dark" })).toBe(false);
  });

  it("cancels on abort, reload and destruction, and rejects invalid requests", async () => {
    const { control, contents, event } = setup();
    const getter = vi.fn(() => "dark");
    for (const input of [{ deliveryId: id(9), operation: "read", theme: "dark" },
      { deliveryId: id(9), operation: "set", theme: "system" },
      { deliveryId: id(9), operation: "read", [Symbol()]: true },
      Object.defineProperty({ deliveryId: id(9), operation: "set" }, "theme", { get: getter })]) {
      expect((await control.request(contents, input as never)).code).toBe("unavailable");
    }
    expect(getter).not.toHaveBeenCalled();
    expect(contents.send).not.toHaveBeenCalled();
    const abort = new AbortController();
    const pending = control.request(contents, { deliveryId: id(), operation: "read" }, abort.signal);
    abort.abort();
    expect((await pending).code).toBe("unavailable");
    const reload = control.request(contents, { deliveryId: id(2), operation: "read" });
    control.invalidate(contents);
    expect((await reload).code).toBe("unavailable");
    const fresh = control.request(contents, { deliveryId: id(3), operation: "read" });
    expect(control.acceptResult(event, { deliveryId: id(2), operation: "read", code: "read", theme: "light" })).toBe(false);
    contents.isDestroyed.mockReturnValue(true);
    control.invalidate(contents);
    expect((await fresh).code).toBe("unavailable");
    const invalid = { deliveryId: id(4), operation: "set", theme: "system" };
    expect((await control.request(contents, invalid as never)).code).toBe("unavailable");
    expect((await control.request(contents, { deliveryId: "INVALID", operation: "read" })).code).toBe("unavailable");
    expect(contents.send).toHaveBeenCalledTimes(3);
  });
});

describe("theme preload boundary", () => {
  it("exposes fixed channels, strips Electron events and removes exactly its listener", async () => {
    const ipc = { on: vi.fn((_channel: string, _listener: (event: unknown, payload: unknown) => void) => undefined),
      removeListener: vi.fn(), invoke: vi.fn(async () => true) };
    const bridge = createAssistantThemePreload(ipc);
    const listener = vi.fn();
    const dispose = bridge.onCommand(listener);
    const wrapped = ipc.on.mock.calls[0][1] as (event: unknown, payload: unknown) => void;
    const payload = { deliveryId: id(), operation: "read" };
    wrapped({ sender: "private" }, payload);
    expect(listener).toHaveBeenCalledWith(payload);
    dispose();
    expect(ipc.removeListener).toHaveBeenCalledWith("vibelution:assistant-theme-command", wrapped);
    await bridge.respond(payload);
    expect(ipc.invoke).toHaveBeenCalledWith("vibelution:assistant-theme-result", payload);
  });
});

describe("AssistantWindow native boundaries", () => {
  async function opened() {
    const { contents, event } = setup();
    const contentEvents = new Map<string, (...args: unknown[]) => void>();
    const windowEvents = new Map<string, (...args: unknown[]) => void>();
    const webContents = { ...contents, setWindowOpenHandler: vi.fn(),
      on: vi.fn((name: string, callback: (...args: unknown[]) => void) => contentEvents.set(name, callback)) };
    const window = { webContents, isDestroyed: vi.fn(() => false), loadURL: vi.fn(async () => undefined),
      showInactive: vi.fn(), on: vi.fn((name: string, callback: (...args: unknown[]) => void) => windowEvents.set(name, callback)) };
    vi.mocked(createPetWindow).mockReturnValue(window as never);
    const owner = new AssistantWindow({ desktopBundleRoot: "unused", userDataRoot: "unused" }, {} as never);
    await owner.open({ show: false });
    return { owner, window, contentEvents, event: { ...event, sender: webContents } };
  }

  it("invalidates deliveries on actual main-frame navigation and destruction", async () => {
    const { owner, contentEvents, event } = await opened();
    const pending = owner.requestTheme({ deliveryId: id(), operation: "read" });
    contentEvents.get("did-start-navigation")?.({}, LAUNCHER_ASSISTANT_URL, false, true);
    expect((await pending).code).toBe("unavailable");
    expect(owner.acceptThemeResult(event, { deliveryId: id(), operation: "read", code: "read", theme: "dark" })).toBe(false);
    const next = owner.requestTheme({ deliveryId: id(2), operation: "read" });
    contentEvents.get("destroyed")?.();
    expect((await next).code).toBe("unavailable");
  });

  it("uses a fixed native image picker and discards cancellation, abort and destroyed-owner results", async () => {
    const { owner, window } = await opened();
    vi.mocked(dialog.showOpenDialog).mockResolvedValue({ canceled: false, filePaths: ["C:\\private-test\\avatar.png"] });
    expect(await owner.chooseOperatorImage("avatar")).toBe("C:\\private-test\\avatar.png");
    expect(dialog.showOpenDialog).toHaveBeenLastCalledWith(window, {
      title: "选择头像", properties: ["openFile"], filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }],
    });
    vi.mocked(dialog.showOpenDialog).mockResolvedValue({ canceled: true, filePaths: [] });
    expect(await owner.chooseOperatorImage("background")).toBeNull();
    let release!: (value: { canceled: boolean; filePaths: string[] }) => void;
    vi.mocked(dialog.showOpenDialog).mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    const abort = new AbortController();
    const pending = owner.chooseOperatorImage("avatar", abort.signal);
    abort.abort(); release({ canceled: false, filePaths: ["C:\\private-test\\late.png"] });
    expect(await pending).toBeNull();
    const calls = vi.mocked(dialog.showOpenDialog).mock.calls.length;
    expect(await owner.chooseOperatorImage("avatar", abort.signal)).toBeNull();
    window.isDestroyed.mockReturnValue(true);
    expect(await owner.chooseOperatorImage("avatar")).toBeNull();
    expect(dialog.showOpenDialog).toHaveBeenCalledTimes(calls);
  });
});
