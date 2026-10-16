import { afterEach, describe, expect, it, vi } from "vitest";
import { controlDesktopAssistant, controlDesktopPet, desktopPetControlBridge, getDesktopAssistantContext, setDesktopPetExpanded } from "./desktopPet";

afterEach(() => vi.unstubAllGlobals());
const capable = { open: false, busyElsewhere: false, mode: null, supportedModes: ["pet", "assistant"] };

describe("desktop companion controls", () => {
  it("requires native assistant context and validates the fixed identity", async () => {
    await expect(getDesktopAssistantContext()).rejects.toThrow("个人助理窗口");
    const context = vi.fn().mockResolvedValueOnce({ role: "desktop-assistant", mode: "assistant" })
      .mockResolvedValueOnce({ role: "main-workbench", mode: "assistant" });
    vi.stubGlobal("vibelutionLauncher", { getDesktopAssistantContext: context });
    await expect(getDesktopAssistantContext()).resolves.toEqual({ role: "desktop-assistant", mode: "assistant" });
    expect(context).toHaveBeenCalledWith();
    await expect(getDesktopAssistantContext()).rejects.toThrow("Invalid");
  });
  it("keeps legacy pet controls compatible", async () => {
    const control = vi.fn(async () => ({ open: true, busyElsewhere: false }));
    vi.stubGlobal("vibelutionLauncher", { controlDesktopPet: control });
    expect(desktopPetControlBridge()).not.toBeNull();
    expect(desktopPetControlBridge({})).toBeNull();
    await expect(controlDesktopPet(true)).resolves.toEqual({ open: true, busyElsewhere: false });
    expect(control).toHaveBeenCalledWith(true);
  });
  it("checks capability before requesting assistant mode", async () => {
    const control = vi.fn().mockResolvedValueOnce(capable).mockResolvedValueOnce({ ...capable, open: true, mode: "assistant" });
    vi.stubGlobal("vibelutionLauncher", { controlDesktopPet: control });
    await expect(controlDesktopAssistant(true)).resolves.toMatchObject({ open: true, mode: "assistant" });
    expect(control.mock.calls).toEqual([[], [true, "assistant"]]);
  });
  it("does not silently open the old pet on a legacy shell", async () => {
    const control = vi.fn(async () => ({ open: false, busyElsewhere: false }));
    vi.stubGlobal("vibelutionLauncher", { controlDesktopPet: control });
    await expect(controlDesktopAssistant(true)).rejects.toThrow("更新桌面壳");
    expect(control).toHaveBeenCalledTimes(1);
  });
  it("does not mutate a companion belonging to another workspace", async () => {
    const control = vi.fn(async () => ({ ...capable, busyElsewhere: true, mode: "assistant" }));
    vi.stubGlobal("vibelutionLauncher", { controlDesktopPet: control });
    await expect(controlDesktopAssistant(false)).resolves.toMatchObject({ busyElsewhere: true });
    expect(control.mock.calls).toEqual([[]]);
  });
  it("rejects malformed states and an incorrect opened mode", async () => {
    const control = vi.fn().mockResolvedValueOnce({ open: "true", busyElsewhere: false })
      .mockResolvedValueOnce(capable).mockResolvedValueOnce({ ...capable, open: true, mode: "pet" });
    vi.stubGlobal("vibelutionLauncher", { controlDesktopPet: control });
    await expect(controlDesktopPet()).rejects.toThrow("Invalid desktop pet state");
    await expect(controlDesktopAssistant(true)).rejects.toThrow("未能打开个人助理窗口");
  });
  it("uses only a boolean resize preset and checks its acknowledgement", async () => {
    const resize = vi.fn().mockResolvedValueOnce({ expanded: true, width: 760, height: 600 })
      .mockResolvedValueOnce({ expanded: true, width: 760, height: 600 });
    vi.stubGlobal("vibelutionLauncher", { setDesktopPetExpanded: resize });
    await expect(setDesktopPetExpanded(true)).resolves.toEqual({ expanded: true, width: 760, height: 600 });
    expect(resize).toHaveBeenCalledWith(true);
    await expect(setDesktopPetExpanded(false)).rejects.toThrow("Invalid");
    vi.stubGlobal("vibelutionLauncher", {});
    await expect(setDesktopPetExpanded(true)).rejects.toThrow("更新桌面壳");
  });
});
