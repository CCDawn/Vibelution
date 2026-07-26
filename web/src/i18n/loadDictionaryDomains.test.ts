import { describe, expect, it } from "vitest";

import { normalizeDictionaryDomains } from "./dictionaryDomainIds";
import { loadDictionaryDomains } from "./loadDictionaryDomains";
import useAppI18nSource from "./useAppI18n.ts?raw";

describe("loadDictionaryDomains (D1)", () => {
  it("always includes core when normalizing domain packs", () => {
    expect(normalizeDictionaryDomains(["evolution"])).toEqual(["core", "evolution"]);
    expect(normalizeDictionaryDomains(["chat", "core"])).toEqual(["core", "chat"]);
  });

  it("loads only requested domain packs at runtime", async () => {
    const evolution = await loadDictionaryDomains(["evolution"]);
    expect(evolution.zh.navEvolution || evolution.zh.appTitle).toBeTruthy();
    expect(evolution.zh.appTitle).toBeTruthy();
    // git-only keys should not be present when git pack is not requested
    expect(evolution.zh.gitPageTitle).toBeUndefined();
  });

  it("loads chat pack without evolution-only keys", async () => {
    const chat = await loadDictionaryDomains(["chat"]);
    expect(chat.zh.navChat || chat.zh.appTitle).toBeTruthy();
    expect(chat.zh.navEvolution).toBeUndefined();
  });

  it("keeps useAppI18n free of static full dictionary imports", () => {
    expect(useAppI18nSource).toContain("loadDictionaryDomains");
    expect(useAppI18nSource).not.toContain('from "./dictionary"');
    expect(useAppI18nSource).toContain("domains");
  });

  it("exposes soft prefetch for navigation warm paths", async () => {
    const { prefetchDictionaryDomains } = await import("./loadDictionaryDomains");
    expect(typeof prefetchDictionaryDomains).toBe("function");
    prefetchDictionaryDomains(["tools"]);
    const tools = await loadDictionaryDomains(["tools"]);
    expect(tools.zh.appTitle || Object.keys(tools.zh).length > 0).toBeTruthy();
  });
});
