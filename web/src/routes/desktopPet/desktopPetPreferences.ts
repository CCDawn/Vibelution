import {
  fetchPersonalAssistantSettings,
  updatePersonalAssistantSettings,
} from "../../api/personalAssistant";
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

// --- Backend authority: the assistant settings API owns the preferences;
// localStorage stays a read cache and an offline fallback. ---

/** Backend preferences, or null when the assistant (or its settings) is absent. */
export async function fetchPetPreferencesFromBackend(): Promise<DesktopPetPreferences | null> {
  const response = await fetchPersonalAssistantSettings();
  return response.settings ? response.settings.preferences : null;
}

/** Backend-first write; rejects with the transport error so callers can explain. */
export async function savePetPreferencesToBackend(value: DesktopPetPreferences): Promise<DesktopPetPreferences> {
  const response = await updatePersonalAssistantSettings({ preferences: value });
  if (!response.settings) throw new Error("个人助理设置暂不可用。");
  return response.settings.preferences;
}

/**
 * Reconcile the local cache with backend authority on mount:
 * backend-unconfigured → upload the local value once (first-run migration);
 * backend-configured → the backend value wins; missing assistant → stay local.
 */
export async function syncPetPreferencesWithBackend(local: DesktopPetPreferences): Promise<DesktopPetPreferences> {
  const response = await fetchPersonalAssistantSettings();
  const settings = response.settings;
  if (!settings) return local;
  if (settings.preferencesConfigured) return settings.preferences;
  try {
    return await savePetPreferencesToBackend(local);
  } catch {
    return local;
  }
}

/** Optimistic local write plus backend-persisted write; flags report each outcome. */
export async function persistPetPreferences(value: DesktopPetPreferences): Promise<{ local: boolean; backend: boolean }> {
  const local = savePetPreferences(value);
  let backend = false;
  try {
    await savePetPreferencesToBackend(value);
    backend = true;
  } catch {
    backend = false;
  }
  return { local, backend };
}
