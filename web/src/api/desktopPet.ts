export type DesktopPetState = { open: boolean; busyElsewhere: boolean };
type PetControlBridge = { controlDesktopPet: (open?: boolean) => Promise<DesktopPetState> };
export function desktopPetControlBridge(source: unknown = globalThis): PetControlBridge | null {
  const bridge = (source as { vibelutionLauncher?: Partial<PetControlBridge> } | null)?.vibelutionLauncher;
  return typeof bridge?.controlDesktopPet === "function" ? bridge as PetControlBridge : null;
}
export async function controlDesktopPet(open?: boolean): Promise<DesktopPetState> {
  const bridge = desktopPetControlBridge();
  if (!bridge) throw new Error("Desktop pet controls require an updated desktop shell");
  const state = await bridge.controlDesktopPet(open);
  if (typeof state?.open !== "boolean" || typeof state?.busyElsewhere !== "boolean") throw new Error("Invalid desktop pet state");
  return state;
}
