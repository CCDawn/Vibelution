import { describe, expect, it, vi } from "vitest";

import {
  isSourceCollectionWorkspaceSelected,
  prefetchTeamsPanelPacks,
  resolveTeamsPanelPrefetchPacks,
} from "./teamPanelPrefetch";

describe("teamPanelPrefetch", () => {
  it("prefers SC pack on knowledge collection surfaces", () => {
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: true,
      }),
    ).toEqual(expect.arrayContaining(["source_collection", "shared"]));
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: true,
      }),
    ).not.toContain("research");
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: true,
      }),
    ).not.toContain("research_experiment");
  });

  it("warms research core (+ experiment on default research views) on non-SC surfaces", () => {
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: false,
        researchWorkspaceView: "overview",
      }),
    ).toEqual(expect.arrayContaining(["research", "research_experiment", "shared"]));
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: false,
        researchWorkspaceView: "canvas",
      }),
    ).toEqual(expect.arrayContaining(["research", "shared"]));
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: false,
        researchWorkspaceView: "canvas",
      }),
    ).not.toContain("research_experiment");
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).not.toContain("source_collection");
  });

  it("warms AI-search pack only for AI search teams (not full research mono)", () => {
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: false,
        aiSearchScopeTeamSelected: true,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).toEqual(expect.arrayContaining(["research_search", "shared"]));
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: false,
        aiSearchScopeTeamSelected: true,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).not.toContain("research");
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: false,
        aiSearchScopeTeamSelected: true,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).not.toContain("research_experiment");
  });

  it("returns empty packs when no matching surface is active", () => {
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: false,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).toEqual([]);
  });

  it("detects SC workspace from view flags", () => {
    expect(
      isSourceCollectionWorkspaceSelected({
        researchWorkflowTeamSelected: true,
        sourceCollectionStandalone: false,
        researchWorkspaceView: "knowledge_collection",
      }),
    ).toBe(true);
    expect(
      isSourceCollectionWorkspaceSelected({
        researchWorkflowTeamSelected: true,
        sourceCollectionStandalone: false,
        researchWorkspaceView: "overview",
      }),
    ).toBe(false);
  });

  it("invokes only selected pack loaders", () => {
    const shared = vi.fn(async () => ({}));
    const research = vi.fn(async () => ({}));
    const research_experiment = vi.fn(async () => ({}));
    const research_search = vi.fn(async () => ({}));
    const source_collection = vi.fn(async () => ({}));
    prefetchTeamsPanelPacks(["research", "research_search", "shared"], {
      shared,
      research,
      research_experiment,
      research_search,
      source_collection,
    });
    expect(shared).toHaveBeenCalledTimes(1);
    expect(research).toHaveBeenCalledTimes(1);
    expect(research_search).toHaveBeenCalledTimes(1);
    expect(research_experiment).not.toHaveBeenCalled();
    expect(source_collection).not.toHaveBeenCalled();
  });
});
