import { describe, expect, it } from "vitest";

import dictionarySource from "../dictionary.ts?raw";
import coreSource from "./dictionaryCore.ts?raw";
import chatSource from "./dictionaryChat.ts?raw";
import evolutionSource from "./dictionaryEvolution.ts?raw";
import gitSource from "./dictionaryGit.ts?raw";
import agentsSource from "./dictionaryAgents.ts?raw";
import agentsWorkbenchSource from "./agentsWorkbenchCopy.ts?raw";
import agentsWorkbenchFacadeSource from "../../routes/agents/agentsRouteCopy.ts?raw";
import loadAgentsWorkbenchSource from "../loadAgentsWorkbenchCopy.ts?raw";

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
    expect(agentsSource).toContain("navAgents:");
  });

  it("keeps Agents workbench nested copy as a structured domain table, not flat TranslationKey", () => {
    expect(agentsWorkbenchSource).toContain("function agentsRouteCopy");
    expect(agentsWorkbenchSource).toContain("title: \"Agent 中心\"");
    expect(agentsWorkbenchFacadeSource).toContain('from "../../i18n/domains/agentsWorkbenchCopy"');
    expect(loadAgentsWorkbenchSource).toContain("prefetchAgentsWorkbenchCopy");
    // Flat dictionaryAgents remains shared + C1.2 high-freq keys; long nested tables stay nested.
    expect(agentsSource).not.toContain("bulkPurgeConfirm:");
    expect(agentsWorkbenchSource).toContain("bulkPurgeConfirm:");
    expect(agentsSource).toContain("agentsWorkbenchTitle:");
    expect(agentsSource).toContain("agentsWorkbenchBulkNoSelection:");
    expect(agentsSource).toContain("agentsWorkbenchBulkArchive:");
    expect(agentsSource).toContain("agentsWorkbenchFilterStatus:");
    expect(agentsSource).toContain("agentsWorkbenchManagementBriefTitle:");
  });
});
