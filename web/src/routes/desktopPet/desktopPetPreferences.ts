import type { DesktopPetCharacterId } from "./desktopPetCharacterModel";

export type DesktopPetPreferences = {
  characterId: DesktopPetCharacterId;
  showStatus: boolean;
  showTitles: boolean;
  showCompletion: boolean;
  idleMessage: string;
};

const KEY = "vibelution.desktop-pet.preferences.v1";
export const DEFAULT_PET_PREFERENCES: DesktopPetPreferences = {
  characterId: "xiaoluo", showStatus: true, showTitles: true,
  showCompletion: true, idleMessage: "",
};

export function readPetPreferences(storage: Pick<Storage, "getItem"> = localStorage): DesktopPetPreferences {
  try {
    const value = JSON.parse(storage.getItem(KEY) ?? "null") as Partial<DesktopPetPreferences> | null;
    return {
      characterId: value?.characterId === "dafeiyu" ? "dafeiyu" : "xiaoluo",
      showStatus: value?.showStatus !== false,
      showTitles: value?.showTitles !== false,
      showCompletion: value?.showCompletion !== false,
      idleMessage: typeof value?.idleMessage === "string" ? value.idleMessage.slice(0, 48) : "",
    };
  } catch {
    return { ...DEFAULT_PET_PREFERENCES };
  }
}

export function savePetPreferences(value: DesktopPetPreferences, storage: Pick<Storage, "setItem"> = localStorage): boolean {
  try {
    storage.setItem(KEY, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
