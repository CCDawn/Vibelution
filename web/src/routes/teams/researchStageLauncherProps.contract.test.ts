import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  flattenResearchStageLauncherProps,
  type TeamResearchStageLauncherPanelProps,
} from "./researchStageLauncherProps";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const primarySurfaceSource = readFileSync(
  new URL("./teamResearchPrimarySurfaceRenderers.tsx", import.meta.url),
  "utf8",
);

function sampleProps(): TeamResearchStageLauncherPanelProps {
  return {
    lang: "zh",
    presentationMode: "interactive",
    team: {
      researchWorkflowSelected: true,
      challengeCupSelected: true,
      knowledgeExpansionSelected: false,
      selected: null,
      memoryMembers: [],
      challengeSurface: "workspace",
      detailDegraded: false,
      detailLoading: false,
      detailQuery: { isFetching: false, refetch: () => undefined },
    },
    sourceCollection: {
      draft: {} as TeamResearchStageLauncherPanelProps["sourceCollection"]["draft"],
      setDraft: (updater) => updater({} as never),
      displayState: { statusText: "idle" },
      selectedRun: null,
      selectedRunEffectiveId: "",
      selectedAssignment: null,
      searchOpenAssignmentCount: 0,
      searchOpenAssignmentCountText: "0",
      executeSearchPending: false,
      acceptedBackgroundActive: false,
      downstreamOpenAssignmentCount: 0,
      downstreamOpenAssignmentCountText: "0",
      pendingScreeningCount: 0,
      startPending: false,
      canStart: false,
      searchActionReadiness: { disabled: true },
      actionInitialDataPending: false,
      actionDataError: false,
      actionBusyReason: "",
      actionNoInputReason: "",
      actionLoadingReason: "",
      actionErrorReason: "",
      actionReadiness: () => ({ disabled: true }),
      executeSearchMutation: { mutate: () => undefined },
      startRunMutation: { mutate: () => undefined },
      collectedCountText: "0",
      displayedCandidateCountText: "0",
      queryCountText: "0",
      runLoopAction: () => undefined,
      loopActionDisabled: true,
      actionDisabledTitle: () => undefined,
      loopActionReadiness: { disabled: true },
      loopActionLabel: "loop",
      loopStartsNewRun: false,
    },
    researchStage: {
      startPending: false,
      canLaunch: false,
      launch: () => undefined,
      roundStatus: null,
      roundStatusQuery: {
        isPending: false,
        isError: false,
        isFetching: false,
        refetch: () => undefined,
      },
      phases: [],
      startError: null,
      startResult: undefined,
      startFeedbackText: () => "",
    },
    experiment: {
      preferredMethod: "",
      setPreferredMethod: () => undefined,
      planningStatus: null,
      planningStatusQuery: {
        isPending: false,
        isFetching: false,
        refetch: () => undefined,
      },
      methodCatalogQuery: { isFetching: false },
    },
    navigation: {
      navigate: (() => undefined) as TeamResearchStageLauncherPanelProps["navigation"]["navigate"],
      searchParams: new URLSearchParams(),
    },
    renderResearchStageAgentSummary: () => null,
  };
}

describe("research stage launcher grouped props", () => {
  it("flattens grouped bags onto stable panel local names", () => {
    const flat = flattenResearchStageLauncherProps(sampleProps());
    expect(flat.researchWorkflowTeamSelected).toBe(true);
    expect(flat.challengeCupResearchTeamSelected).toBe(true);
    expect(flat.presentationMode).toBe("interactive");
    expect(flat.sourceCollectionCanStart).toBe(false);
    expect(flat.sourceCollectionLoopActionLabel).toBe("loop");
    expect(flat.lang).toBe("zh");
  });

  it("primary surface factory mounts the launcher with grouped bags, not a flat 60-key spray", () => {
    // Launcher JSX lives in teamResearchPrimarySurfaceRenderers (extracted from TeamsRoute).
    expect(routeSource).toContain("renderResearchStageLauncher");
    expect(primarySurfaceSource).toContain("function renderResearchStageLauncher");
    const launcherFn = primarySurfaceSource.slice(
      primarySurfaceSource.indexOf("function renderResearchStageLauncher"),
      primarySurfaceSource.indexOf("function renderResearchOverviewSurface"),
    );
    expect(launcherFn).toContain("sourceCollection={{");
    expect(launcherFn).toContain("researchStage={{");
    expect(launcherFn).toContain("experiment={{");
    expect(launcherFn).toContain("navigation={{");
    expect(launcherFn).toContain("team={{");
    // Flat legacy keys must not reappear on the launcher mount.
    expect(launcherFn).not.toContain("sourceCollectionDraft={sourceCollectionDraft}");
    expect(launcherFn).not.toContain("researchWorkflowTeamSelected={researchWorkflowTeamSelected}");
    expect(launcherFn).not.toContain("selectedTeamStartResearchStagePending={");
  });
});
