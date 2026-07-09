import { describe, expect, it } from "vitest";

import typesBarrelSource from "./types.ts?raw";
import agentsTypesSource from "./types/agents.ts?raw";
import chatTypesSource from "./types/chat.ts?raw";
import configTypesSource from "./types/config.ts?raw";
import evolutionTypesSource from "./types/evolution.ts?raw";
import memoryTypesSource from "./types/memory.ts?raw";
import runtimeTypesSource from "./types/runtime.ts?raw";
import sharedTypesSource from "./types/shared.ts?raw";
import teamsTypesSource from "./types/teams.ts?raw";

const expectedBarrel = [
  'export * from "./types/shared";',
  'export * from "./types/chat";',
  'export * from "./types/teams";',
  'export * from "./types/agents";',
  'export * from "./types/runtime";',
  'export * from "./types/memory";',
  'export * from "./types/evolution";',
  'export * from "./types/config";',
].join("\n");

const domainSources = [
  agentsTypesSource,
  chatTypesSource,
  configTypesSource,
  evolutionTypesSource,
  memoryTypesSource,
  runtimeTypesSource,
  sharedTypesSource,
  teamsTypesSource,
];

describe("api type domain modules", () => {
  it("keeps types.ts as the public compatibility barrel", () => {
    expect(typesBarrelSource.trim()).toBe(expectedBarrel);
    expect(typesBarrelSource).not.toMatch(/^export\s+(type|interface)\s+/m);
  });

  it("keeps high-churn DTO families in their domain modules", () => {
    expect(chatTypesSource).toContain("export type SessionDetail");
    expect(chatTypesSource).toContain("export type ChatRoomDetail");
    expect(teamsTypesSource).toContain("export type TeamWorkflowSourceCollectionRunStartPayload");
    expect(agentsTypesSource).toContain("export type AgentInstance");
    expect(runtimeTypesSource).toContain("export type RuntimeSummary");
    expect(memoryTypesSource).toContain("export type MemoryOverview");
    expect(evolutionTypesSource).toContain("export type EvolutionOverview");
    expect(configTypesSource).toContain("export type ConfigSummary");
  });

  it("keeps cross-domain dependencies type-only", () => {
    for (const source of domainSources) {
      expect(source).not.toMatch(/^import\s+(?!type\b)/m);
    }
  });
});
