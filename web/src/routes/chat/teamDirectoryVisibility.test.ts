import { describe, expect, it } from "vitest";
import { loadHiddenTeamIds, normalizeHiddenTeamIds, saveHiddenTeamIds } from "./teamDirectoryVisibility";

describe("team directory visibility", () => {
  it("round-trips browser preferences without altering Team data", () => {
    const data = new Map<string, string>();
    const storage = { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value); } };
    saveHiddenTeamIds(["team-a", "team-b", "team-a"], storage);
    expect(loadHiddenTeamIds(storage)).toEqual(["team-a", "team-b"]);
    saveHiddenTeamIds(["team-b"], storage);
    expect(loadHiddenTeamIds(storage)).toEqual(["team-b"]);
  });
  it("recovers from corrupted or blocked storage and ignores malformed ids", () => {
    expect(normalizeHiddenTeamIds([" team-a ", "", 3, null, "team-a"])).toEqual(["team-a"]);
    expect(loadHiddenTeamIds({ getItem: () => "{", setItem: () => undefined })).toEqual([]);
    expect(loadHiddenTeamIds({ getItem: () => { throw new Error("denied"); }, setItem: () => undefined })).toEqual([]);
    expect(() => saveHiddenTeamIds(["team-a"], { getItem: () => null, setItem: () => { throw new Error("denied"); } })).not.toThrow();
  });
});
