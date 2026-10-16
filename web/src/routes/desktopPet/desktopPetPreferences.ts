import type { DesktopPetCharacterId } from "./desktopPetCharacterModel";

export type DesktopPetPreferences = {
  characterId: DesktopPetCharacterId;
  showStatus: boolean;
  showTitles: boolean;
  showCompletion: boolean;
  idleMessage: string;
};

const KEY = "vibelution.desktop-pet.preferences.v1";
// The unified assistant body defaults to the whale rig; Xiao Luo Live2D stays
// a selectable appearance. Stored preferences (including xiaoluo) are honored.
export const DEFAULT_PET_PREFERENCES: DesktopPetPreferences = {
  characterId: "dafeiyu", showStatus: true, showTitles: true,
  showCompletion: true, idleMessage: "",
};

export function readPetPreferences(storage?: Pick<Storage, "getItem">): DesktopPetPreferences {
  try {
    const value = JSON.parse((storage ?? localStorage).getItem(KEY) ?? "null") as Partial<DesktopPetPreferences> | null;
    return {
      characterId: value?.characterId === "xiaoluo" ? "xiaoluo" : "dafeiyu",
      showStatus: value?.showStatus !== false,
      showTitles: value?.showTitles !== false,
      showCompletion: value?.showCompletion !== false,
      idleMessage: typeof value?.idleMessage === "string" ? value.idleMessage.slice(0, 48) : "",
    };
  } catch {
    return { ...DEFAULT_PET_PREFERENCES };
  }
}

export function savePetPreferences(value: DesktopPetPreferences, storage?: Pick<Storage, "setItem">): boolean {
  try {
    (storage ?? localStorage).setItem(KEY, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
