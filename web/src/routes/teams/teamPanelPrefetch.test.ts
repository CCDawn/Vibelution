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
  });

  it("prefers research pack on research overview / non-SC surfaces", () => {
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).toEqual(expect.arrayContaining(["research", "shared"]));
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: true,
        aiSearchScopeTeamSelected: false,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).not.toContain("source_collection");
  });

  it("warms research pack for AI search team", () => {
    expect(
      resolveTeamsPanelPrefetchPacks({
        researchWorkflowTeamSelected: false,
        aiSearchScopeTeamSelected: true,
        sourceCollectionWorkspaceSelected: false,
      }),
    ).toEqual(expect.arrayContaining(["research", "shared"]));
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
    const source_collection = vi.fn(async () => ({}));
    prefetchTeamsPanelPacks(["research", "shared"], { shared, research, source_collection });
    expect(shared).toHaveBeenCalledTimes(1);
    expect(research).toHaveBeenCalledTimes(1);
    expect(source_collection).not.toHaveBeenCalled();
  });
});
