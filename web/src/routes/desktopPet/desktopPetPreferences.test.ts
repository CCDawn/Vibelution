import { describe, expect, it } from "vitest";
import { DEFAULT_PET_PREFERENCES, readPetPreferences, savePetPreferences } from "./desktopPetPreferences";

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
});
