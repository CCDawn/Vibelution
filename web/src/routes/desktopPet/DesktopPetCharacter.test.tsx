// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Live2dModule, Live2dStatus } from "./live2dContract";
import type { PetAnimationState } from "../../api/types/petActivity";
import { DesktopPetCharacter } from "./DesktopPetCharacter";
const mock = vi.hoisted(() => ({ load: vi.fn(), setState: vi.fn(), dispose: vi.fn(), create: vi.fn() }));
vi.mock("./loadLive2d", () => ({ loadLive2d: mock.load }));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
let root: Root, host: HTMLDivElement;
let resolve: (module: Live2dModule) => void;
beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  mock.load.mockImplementation(() => new Promise<Live2dModule>(done => { resolve = done; }));
  mock.create.mockImplementation((_canvas, _state, report: (status: Live2dStatus) => void) => {
    report("ready"); return { setState: mock.setState, dispose: mock.dispose };
  });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function render(state: PetAnimationState = "idle") {
  await act(async () => root.render(<DesktopPetCharacter characterId="xiaoluo" name="小洛" tone="idle" animationState={state} />));
}
async function ready() { await act(async () => resolve({ createLive2dController: mock.create })); }
describe("Live2D desktop pet", () => {
  it("loads the real canvas and shows an explicit loading state, not the retired PNG", async () => {
    await render();
    expect(host.querySelector("canvas")).not.toBeNull();
    expect(host.textContent).toContain("正在加载 Live2D");
    expect(host.querySelector("img")).toBeNull();
    await ready();
    expect(host.querySelector("[data-renderer-status=ready]")).not.toBeNull();
    expect(host.textContent).toContain("小洛 · 火爆鸡王");
  });
  it("uses the newest state when model loading finishes", async () => {
    await render("idle"); await render("thinking"); await ready();
    expect(mock.create.mock.calls[0][1]).toBe("thinking");
  });
  it("updates activity without rebuilding the WebGL renderer", async () => {
    await render(); await ready(); await render("reading"); await render("celebrating");
    expect(mock.create).toHaveBeenCalledTimes(1);
    expect(mock.setState).toHaveBeenLastCalledWith("celebrating");
  });
  it("releases the renderer on close", async () => {
    await render(); await ready(); await act(async () => root.unmount());
    expect(mock.dispose).toHaveBeenCalledTimes(1);
  });
  it("does not create a renderer after the window/component has closed", async () => {
    await render(); await act(async () => root.unmount()); await ready();
    expect(mock.create).not.toHaveBeenCalled();
  });
  it("reports asset failures and keeps the old image retired", async () => {
    mock.load.mockRejectedValueOnce(new Error("missing Core"));
    await render();
    expect(host.textContent).toContain("Live2D 加载失败");
    expect(host.querySelector("img")).toBeNull();
  });

  it("switches to the approved Dafeiyu layered rig without booting Cubism", async () => {
    await act(async () => root.render(
      <DesktopPetCharacter
        characterId="dafeiyu"
        name="大肥鲸"
        tone="idle"
        animationState="idle"
      />,
    ));
    const frame = host.querySelector<HTMLIFrameElement>("iframe");
    expect(frame?.getAttribute("src")).toBe("/desktop-pet/whale-rig/index.html?embed=1");
    expect(frame?.getAttribute("title")).toBe("大肥鲸 2.5D 桌面伙伴");
    expect(host.textContent).toContain("正在加载大肥鲸");
    expect(mock.load).not.toHaveBeenCalled();
  });
});
