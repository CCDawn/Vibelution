import { describe, expect, it } from "vitest";

import { dictionaryAgents } from "./domains/dictionaryAgents";
import { agentsRouteCopy } from "./domains/agentsWorkbenchCopy";
import { mergeAgentsRouteCopyWithDictionary } from "./mergeAgentsWorkbenchCopy";

describe("mergeAgentsRouteCopyWithDictionary", () => {
  it("overlays high-frequency flat dictionary keys when available", () => {
    const base = agentsRouteCopy("zh");
    const t = (key: string) => dictionaryAgents.zh[key as keyof typeof dictionaryAgents.zh] ?? key;
    const merged = mergeAgentsRouteCopyWithDictionary(base, t as never);
    expect(merged.title).toBe(dictionaryAgents.zh.agentsWorkbenchTitle);
    expect(merged.refresh).toBe(dictionaryAgents.zh.agentsWorkbenchRefresh);
    expect(merged.bulkNoSelection).toBe(dictionaryAgents.zh.agentsWorkbenchBulkNoSelection);
    expect(merged.bulkArchive).toBe(dictionaryAgents.zh.agentsWorkbenchBulkArchive);
    expect(merged.filterSections.status).toBe(dictionaryAgents.zh.agentsWorkbenchFilterStatus);
    expect(merged.managementBriefTitle).toBe(dictionaryAgents.zh.agentsWorkbenchManagementBriefTitle);
    // Nested-only fields stay from workbench table.
    expect(merged.bulkArchiveConfirm).toBe(base.bulkArchiveConfirm);
  });

  it("falls back to nested workbench copy when dictionary key is unloaded", () => {
    const base = agentsRouteCopy("en");
    const t = (key: string) => key;
    const merged = mergeAgentsRouteCopyWithDictionary(base, t as never);
    expect(merged.title).toBe(base.title);
    expect(merged.search).toBe(base.search);
  });
});
