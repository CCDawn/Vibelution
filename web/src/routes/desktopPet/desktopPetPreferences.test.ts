import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_PET_PREFERENCES,
  fetchPetPreferencesFromBackend,
  persistPetPreferences,
  readPetPreferences,
  savePetPreferences,
  syncPetPreferencesWithBackend,
} from "./desktopPetPreferences";
import {
  fetchPersonalAssistantSettings as fetchSettings,
  updatePersonalAssistantSettings as updateSettings,
} from "../../api/personalAssistant";

vi.mock("../../api/personalAssistant", () => ({
  fetchPersonalAssistantSettings: vi.fn(),
  updatePersonalAssistantSettings: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("desktop pet preferences", () => {
  it("restores character, privacy, completion and copy after reopening", () => {
    let stored = "";
    const storage = { getItem: () => stored, setItem: (_key: string, value: string) => { stored = value; } };
    const prefs = { ...DEFAULT_PET_PREFERENCES, characterId: "dafeiyu" as const, showTitles: false, showCompletion: false, idleMessage: "在这里陪你" };
    expect(savePetPreferences(prefs, storage)).toBe(true);
    expect(readPetPreferences(storage)).toEqual(prefs);
  });
  it("handles unavailable or malformed storage and reports save failure", () => {
    expect(readPetPreferences({ getItem: () => "{" })).toEqual(DEFAULT_PET_PREFERENCES);
    expect(savePetPreferences(DEFAULT_PET_PREFERENCES, { setItem: () => { throw new Error("denied"); } })).toBe(false);
  });
  it("falls back when browser storage is unavailable", () => {
    vi.stubGlobal("localStorage", undefined);
    try {
      expect(readPetPreferences()).toEqual(DEFAULT_PET_PREFERENCES);
      expect(savePetPreferences(DEFAULT_PET_PREFERENCES)).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("desktop pet preferences backend authority", () => {
  it("prefers configured backend preferences over the local cache", async () => {
    const backend = { ...DEFAULT_PET_PREFERENCES, characterId: "xiaoluo" as const, showTitles: false };
    fetchSettings.mockResolvedValue({ settings: { displayName: "个人助理", preferences: backend, preferencesConfigured: true,
      model: { currentModelId: "", choices: [] } } });
    const local = { ...DEFAULT_PET_PREFERENCES };
    await expect(syncPetPreferencesWithBackend(local)).resolves.toEqual(backend);
    expect(fetchSettings).toHaveBeenCalled();
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("migrates the local cache up once when the backend was never configured", async () => {
    fetchSettings.mockResolvedValue({ settings: { displayName: "个人助理", preferences: DEFAULT_PET_PREFERENCES,
      preferencesConfigured: false, model: { currentModelId: "", choices: [] } } });
    updateSettings.mockResolvedValue({ settings: { displayName: "个人助理", preferences: { ...DEFAULT_PET_PREFERENCES, idleMessage: "在这里陪你" },
      preferencesConfigured: true, model: { currentModelId: "", choices: [] } } });
    const local = { ...DEFAULT_PET_PREFERENCES, idleMessage: "在这里陪你" };
    await expect(syncPetPreferencesWithBackend(local)).resolves.toEqual(local);
    expect(updateSettings).toHaveBeenCalledWith({ preferences: local });
  });

  it("keeps local preferences when the migration upload fails or the assistant is missing", async () => {
    fetchSettings.mockResolvedValue({ settings: { displayName: "个人助理", preferences: DEFAULT_PET_PREFERENCES,
      preferencesConfigured: false, model: { currentModelId: "", choices: [] } } });
    updateSettings.mockRejectedValue(new Error("offline"));
    const local = { ...DEFAULT_PET_PREFERENCES, showStatus: false };
    await expect(syncPetPreferencesWithBackend(local)).resolves.toEqual(local);
    fetchSettings.mockResolvedValue({ settings: null });
    await expect(syncPetPreferencesWithBackend(local)).resolves.toEqual(local);
  });

  it("reports local and backend write outcomes separately", async () => {
    const entries: Array<[string, string]> = [];
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: (key: string, value: string) => { entries.push([key, value]); },
    });
    try {
      const value = { ...DEFAULT_PET_PREFERENCES, characterId: "xiaoluo" as const };
      updateSettings.mockResolvedValue({ settings: { displayName: "个人助理", preferences: value,
        preferencesConfigured: true, model: { currentModelId: "", choices: [] } } });
      await expect(persistPetPreferences(value)).resolves.toEqual({ local: true, backend: true });
      expect(entries).toHaveLength(1);
      updateSettings.mockRejectedValue(new Error("offline"));
      await expect(persistPetPreferences(value)).resolves.toEqual({ local: true, backend: false });
      fetchSettings.mockResolvedValue({ settings: { displayName: "个人助理", preferences: value,
        preferencesConfigured: true, model: { currentModelId: "", choices: [] } } });
      await expect(fetchPetPreferencesFromBackend()).resolves.toEqual(value);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
