import type { ManagedWindowState } from "./windowProviderTypes.js";

type PetWindowOwner = {
  snapshot(): { pet: ManagedWindowState };
  openPet(url: string): Promise<ManagedWindowState>;
  closePet(): Promise<ManagedWindowState>;
};

export type DesktopPetMode = "pet" | "assistant";
const supportedModes: DesktopPetMode[] = ["pet", "assistant"];

function windowMode(state: ManagedWindowState): DesktopPetMode | null {
  if (!state.open) return null;
  return new URL(state.url).pathname === "/desktop-assistant" ? "assistant" : "pet";
}

export function petSettingsOrigin(url: string, role: string): string {
  // Any SPA route inside a registered workbench window may control the pet; the
  // settings popover mounts on arbitrary routes, so only the window role gates.
  const parsed = new URL(url);
  if (!["main-workbench", "branch-workbench"].includes(role)) {
    throw new Error("Desktop pet controls require a registered settings window");
  }
  return parsed.origin;
}

/** Serialize requests so another workspace cannot take over a pet being opened. */
export function createPetSettingsControl(getOwner: () => PetWindowOwner | null | undefined) {
  let tail: Promise<unknown> = Promise.resolve();
  return (origin: string, open: unknown, mode?: unknown) => {
    const result = tail.then(async () => {
      if (open !== undefined && typeof open !== "boolean") throw new Error("Invalid pet visibility");
      if (mode !== undefined && mode !== "pet" && mode !== "assistant") throw new Error("Invalid pet mode");
      const owner = getOwner();
      if (!owner) throw new Error("Desktop shell is not ready");
      const current = owner.snapshot().pet;
      const busyElsewhere = current.open && new URL(current.url).origin !== origin;
      if (busyElsewhere) return { open: false, busyElsewhere: true, mode: windowMode(current), supportedModes: [...supportedModes] };
      const targetUrl = mode === "assistant" ? `${origin}/desktop-assistant` : origin;
      const next = typeof open === "boolean"
        ? await (open ? owner.openPet(targetUrl) : owner.closePet()) : current;
      return { open: next.open, busyElsewhere: false, mode: windowMode(next), supportedModes: [...supportedModes] };
    });
    tail = result.catch(() => undefined);
    return result;
  };
}
