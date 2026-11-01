export type DesktopPetMode = "pet" | "assistant";
export type DesktopPetState = {
  open: boolean;
  busyElsewhere: boolean;
  /** Optional for compatibility with desktop shells predating assistant mode. */
  mode?: DesktopPetMode | null;
  supportedModes?: DesktopPetMode[];
};
export type DesktopPetExpandedState = { expanded: boolean; width: number; height: number };
type PetControlBridge = { controlDesktopPet: (open?: boolean, mode?: DesktopPetMode) => Promise<DesktopPetState> };
type PetExpandedBridge = { setDesktopPetExpanded: (expanded: boolean) => Promise<DesktopPetExpandedState> };
export function desktopPetControlBridge(source: unknown = globalThis): PetControlBridge | null {
  const bridge = (source as { vibelutionLauncher?: Partial<PetControlBridge> } | null)?.vibelutionLauncher;
  return typeof bridge?.controlDesktopPet === "function" ? bridge as PetControlBridge : null;
}
function validDesktopPetState(state: DesktopPetState): DesktopPetState {
  if (typeof state?.open !== "boolean" || typeof state?.busyElsewhere !== "boolean"
    || (state.mode !== undefined && state.mode !== null && state.mode !== "pet" && state.mode !== "assistant")
    || (state.supportedModes !== undefined && (!Array.isArray(state.supportedModes)
      || state.supportedModes.some(mode => mode !== "pet" && mode !== "assistant")))) {
    throw new Error("Invalid desktop pet state");
  }
  return state;
}

export async function controlDesktopPet(open?: boolean): Promise<DesktopPetState> {
  const bridge = desktopPetControlBridge();
  if (!bridge) throw new Error("Desktop pet controls require an updated desktop shell");
  return validDesktopPetState(await bridge.controlDesktopPet(open));
}

/** Available only inside the registered floating window, with fixed size presets. */
export async function setDesktopPetExpanded(expanded: boolean): Promise<DesktopPetExpandedState> {
  const bridge = (globalThis as { vibelutionLauncher?: Partial<PetExpandedBridge> }).vibelutionLauncher;
  if (typeof bridge?.setDesktopPetExpanded !== "function") throw new Error("个人助理展开需要更新桌面壳。");
  const state = await bridge.setDesktopPetExpanded(expanded);
  if (state?.expanded !== expanded || !Number.isFinite(state.width) || state.width <= 0
    || !Number.isFinite(state.height) || state.height <= 0) throw new Error("Invalid desktop pet expanded state");
  return state;
}
