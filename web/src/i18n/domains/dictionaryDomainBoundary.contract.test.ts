import { describe, expect, it } from "vitest";

import dictionarySource from "../dictionary.ts?raw";
import coreSource from "./dictionaryCore.ts?raw";
import chatSource from "./dictionaryChat.ts?raw";
import evolutionSource from "./dictionaryEvolution.ts?raw";
import gitSource from "./dictionaryGit.ts?raw";

describe("dictionary domain boundary", () => {
  it("keeps dictionary.ts as a merge façade over domain slices", () => {
    expect(dictionarySource).toContain('from "./domains/dictionaryCore"');
    expect(dictionarySource).toContain('from "./domains/dictionaryChat"');
    expect(dictionarySource).toContain('from "./domains/dictionaryEvolution"');
    expect(dictionarySource).toContain("...dictionaryCore.zh");
    expect(dictionarySource).toContain("...dictionaryEvolution.zh");
    expect(dictionarySource).not.toMatch(/appTitle:\s*"/);
  });

  it("owns domain-heavy keys in their slices", () => {
    expect(coreSource).toContain("appTitle:");
    expect(chatSource).toContain("navChat:");
    expect(evolutionSource).toContain("navEvolution:");
    expect(gitSource).toContain("gitPageTitle:");
  });
});
