import { afterEach, describe, expect, it, vi } from "vitest";
import { controlDesktopPet, desktopPetControlBridge, getDesktopAssistantContext, setDesktopPetExpanded } from "./desktopPet";

afterEach(() => vi.unstubAllGlobals());

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
  it("rejects malformed states", async () => {
    const control = vi.fn(async () => ({ open: "true", busyElsewhere: false }));
    vi.stubGlobal("vibelutionLauncher", { controlDesktopPet: control });
    await expect(controlDesktopPet()).rejects.toThrow("Invalid desktop pet state");
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
