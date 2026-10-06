import { describe, expect, it } from "vitest";
import {
  EMPTY_FINANCE_SCREEN_PRESET_FILTERS,
  MAX_FINANCE_SCREEN_PRESETS,
  financeScreenPresetStorageKey,
  readFinanceScreenPresets,
  writeFinanceScreenPresets,
  type FinanceScreenPreset,
} from "./financeScreenPresets";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

function preset(id: string, name = id): FinanceScreenPreset {
  return { id, name, filters: { ...EMPTY_FINANCE_SCREEN_PRESET_FILTERS, minPb: "1.2", minTurnoverYi: "10" } };
}

describe("financeScreenPresets", () => {
  it("stores and reads independent Agent-scoped criteria only", () => {
    const storage = new MemoryStorage();
    expect(writeFinanceScreenPresets("agent/one", [preset("value")], storage)).toBe(true);
    expect(readFinanceScreenPresets("agent/one", storage)).toEqual([preset("value")]);
    expect(readFinanceScreenPresets("agent/two", storage)).toEqual([]);
    expect(financeScreenPresetStorageKey("agent/one")).toContain("agent%2Fone");
    expect(writeFinanceScreenPresets(" ", [preset("ignored")], storage)).toBe(false);
  });

  it("limits saved groups and safely normalizes malformed storage entries", () => {
    const storage = new MemoryStorage();
    const many = Array.from({ length: MAX_FINANCE_SCREEN_PRESETS + 5 }, (_, index) => preset(`preset-${index}`));
    expect(writeFinanceScreenPresets("agent", many, storage)).toBe(true);
    expect(readFinanceScreenPresets("agent", storage)).toHaveLength(MAX_FINANCE_SCREEN_PRESETS);

    storage.setItem(financeScreenPresetStorageKey("agent"), JSON.stringify([
      { id: "bad", name: "", filters: {} },
      { id: "good", name: "  usable  ", filters: { minPrice: "not-a-number", minPb: "2.3", sortBy: "bad" } },
      { id: "good", name: "duplicate id", filters: {} },
    ]));
    expect(readFinanceScreenPresets("agent", storage)).toEqual([{
      id: "good", name: "usable", filters: { ...EMPTY_FINANCE_SCREEN_PRESET_FILTERS, minPb: "2.3" },
    }]);
  });

  it("returns a storage failure when browser persistence rejects writes", () => {
    const storage = {
      getItem: () => null,
      setItem: () => { throw new Error("quota"); },
    };
    expect(writeFinanceScreenPresets("agent", [preset("one")], storage)).toBe(false);
    expect(readFinanceScreenPresets("agent", { getItem: () => "invalid-json", setItem: () => {} })).toEqual([]);
  });
});
