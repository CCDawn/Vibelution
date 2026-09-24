import type { ManagedWindowState } from "./windowProviderTypes.js";

type PetWindowOwner = {
  snapshot(): { pet: ManagedWindowState };
  openPet(url: string): Promise<ManagedWindowState>;
  closePet(): Promise<ManagedWindowState>;
};

export function petSettingsOrigin(url: string, role: string): string {
  const parsed = new URL(url);
  if (!["main-workbench", "branch-workbench"].includes(role) || parsed.pathname !== "/config") {
    throw new Error("Desktop pet controls require a registered settings window");
  }
  return parsed.origin;
}

/** Serialize requests so another workspace cannot take over a pet being opened. */
export function createPetSettingsControl(getOwner: () => PetWindowOwner | null | undefined) {
  let tail: Promise<unknown> = Promise.resolve();
  return (origin: string, open: unknown) => {
    const result = tail.then(async () => {
      if (open !== undefined && typeof open !== "boolean") throw new Error("Invalid pet visibility");
      const owner = getOwner();
      if (!owner) throw new Error("Desktop shell is not ready");
      const current = owner.snapshot().pet;
      const busyElsewhere = current.open && new URL(current.url).origin !== origin;
      if (busyElsewhere) return { open: false, busyElsewhere: true };
      const next = typeof open === "boolean"
        ? await (open ? owner.openPet(origin) : owner.closePet()) : current;
      return { open: next.open, busyElsewhere: false };
    });
    tail = result.catch(() => undefined);
    return result;
  };
}
