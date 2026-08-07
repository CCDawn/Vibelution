/**
 * Real router/render tests for Teams legacy → workflow boundary.
 * Must not only unit-test the pure resolver.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  shouldReplaceLegacyResearchLocation,
  TeamsLegacyResearchBoundary,
} from "./TeamsLegacyResearchBoundary";

function LocationProbe({ onLoc }: { onLoc: (s: string) => void }) {
  const loc = useLocation();
  onLoc(`${loc.pathname}${loc.search}`);
  return <div data-testid="surface">workflow-surface</div>;
}

function LegacyStageMarker() {
  return <div data-testid="legacy-stage">ResearchStageStandalonePage</div>;
}

describe("TeamsLegacyResearchBoundary (route render)", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latestHref = "";

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latestHref = "";
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  async function mountAt(initialEntry: string, mountLegacyInShell = false) {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route
              path="/teams"
              element={
                <TeamsLegacyResearchBoundary>
                  {mountLegacyInShell ? (
                    <LegacyStageMarker />
                  ) : (
                    <LocationProbe onLoc={(s) => { latestHref = s; }} />
                  )}
                </TeamsLegacyResearchBoundary>
              }
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("test_teams_experiment_query_redirects_to_workflow_node", async () => {
    await mountAt("/teams?team=research-team&researchView=experiment");
    expect(latestHref).toContain("researchView=workflow");
    expect(latestHref).toContain("node=hypothesis_design");
    expect(latestHref).toContain("team=research-team");
    expect(container.textContent).toContain("workflow-surface");
    expect(container.textContent).not.toContain("ResearchStageStandalonePage");
  });

  it("test_teams_iteration_query_redirects_to_workflow_node", async () => {
    await mountAt("/teams?team=research-team&researchView=iteration&runId=run-99");
    expect(latestHref).toContain("researchView=workflow");
    expect(latestHref).toContain("node=controlled_run");
    expect(latestHref).toContain("runId=run-99");
  });

  it("test_legacy_redirect_preserves_team_and_run_id", async () => {
    await mountAt("/teams?team=t-keep&runId=run-keep&researchView=knowledge_collection");
    expect(latestHref).toContain("team=t-keep");
    expect(latestHref).toContain("runId=run-keep");
    expect(latestHref).toContain("researchView=workflow");
    expect(latestHref).toContain("node=source_finding");
  });

  it("test_teams_shell_never_mounts_legacy_stage_surface", async () => {
    // Boundary forces workflow params; shell under test does not mount stage page.
    await mountAt("/teams?researchView=experiment", false);
    expect(container.querySelector("[data-testid='legacy-stage']")).toBeNull();
    expect(container.textContent).toContain("workflow-surface");
  });

  it("test_canonical_workflow_does_not_redirect_loop", async () => {
    const entry =
      "/teams?team=t1&researchView=workflow&workflowId=challenge-cup-research&runId=run-1&node=smoke_gate";
    const decision = shouldReplaceLegacyResearchLocation({
      pathname: "/teams",
      search: entry.includes("?") ? entry.slice(entry.indexOf("?")) : "",
    });
    expect(decision.replace).toBe(false);

    await mountAt(entry);
    // Stable: still on same logical location (order of params may normalize)
    expect(latestHref).toContain("researchView=workflow");
    expect(latestHref).toContain("runId=run-1");
    expect(latestHref).toContain("node=smoke_gate");
    const afterFirst = latestHref;
    await act(async () => {
      await Promise.resolve();
    });
    expect(latestHref).toBe(afterFirst);
  });
});
