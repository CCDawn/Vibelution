import { describe, expect, it } from "vitest";

import persistedHeightListShellSource from "../components/layout/PersistedHeightListShell.tsx?raw";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import activeStageSource from "./TeamSourceCollectionActiveStagePanel.tsx?raw";
import activeStageStyles from "./TeamSourceCollectionActiveStagePanel.styles";
import panelFrameStyles from "./TeamSourceCollectionPanelFrame.styles";
import screeningPanelSource from "./TeamSourceCollectionScreeningPanel.tsx?raw";
import screeningPanelStyles from "./TeamSourceCollectionScreeningPanel.styles";
import standaloneStageSource from "./TeamSourceCollectionStandaloneStagePanel.tsx?raw";
import standaloneStageStyles from "./TeamSourceCollectionStandaloneStagePanel.styles";
import { SOURCE_COLLECTION_RESULT_PAGE_SIZE } from "./teams/source-collection/presentationModel";

describe("source collection vertical three-column workbench", () => {
  it("uses persisted VSplitWorkspace rails instead of fixed clamp grid columns", () => {
    expect(standaloneStageSource).toContain("VSplitWorkspace");
    expect(standaloneStageSource).toContain("WORKBENCH_LAYOUT_IDS.teamsSourceCollection");
    expect(standaloneStageSource).toContain('id: "sc-left"');
    expect(standaloneStageStyles.sourceCollectionPageBody).toContain("flex");
    expect(standaloneStageStyles.sourceCollectionPageBody).not.toContain("grid-cols-[clamp");
    expect(standaloneStageStyles.sourceCollectionLeftRail).not.toContain("col-start-1");

    expect(activeStageSource).toContain("VSplitWorkspace");
    expect(activeStageSource).toContain("WORKBENCH_LAYOUT_IDS.teamsSourceCollectionStage");
    expect(activeStageSource).toContain('id: "sc-stage"');
    expect(activeStageStyles.sourceCollectionStageWorkspace).toContain("flex");
    expect(activeStageStyles.sourceCollectionStageWorkspace).not.toContain("grid-cols-[minmax(0,1fr)_clamp");
    expect(WORKBENCH_LAYOUT_IDS.teamsSourceCollection).toBe("teams-source-collection");
    expect(WORKBENCH_LAYOUT_IDS.teamsSourceCollectionStage).toBe("teams-source-collection-stage");
  });

  it("keeps stage navigation free of duplicated long action buttons", () => {
    expect(standaloneStageSource).not.toContain("actions={");
    // Standalone imports VSplitWorkspace from vui; still no VButton spray.
    expect(standaloneStageSource).not.toContain("VButton");
  });

  it("groups errors and results into explicit surfaces", () => {
    expect(activeStageSource).toContain("sourceCollectionStageErrors");
    expect(activeStageSource).toContain("sourceCollectionStageResult");
    expect(activeStageStyles.sourceCollectionStageChatActions).toContain(
      "grid-cols-[repeat(2,minmax(0,1fr))]",
    );
  });

  it("uses the available extraction workspace before paginating source material", () => {
    expect(SOURCE_COLLECTION_RESULT_PAGE_SIZE).toBe(16);
    expect(activeStageStyles.sourceCollectionExtractionPanels).toContain("h-full");
    expect(activeStageStyles.sourceCollectionExtractionScrollRegion).toContain("overflow-auto");
    expect(screeningPanelStyles.sourceCollectionExpandedContentPanel).toContain("overflow-visible");
    expect(screeningPanelStyles.sourceCollectionScreeningListShell).toContain("self-start");
    expect(screeningPanelSource).toContain("expandToContent");
    expect(persistedHeightListShellSource).toContain("expandToContent");
    expect(persistedHeightListShellSource).toContain('height: "auto"');
    expect(persistedHeightListShellSource).toContain("expandToContent ? null");
  });

  it("keeps the transient focused state visual without changing panel layout", () => {
    expect(panelFrameStyles.sourceCollectionFocusedPanel).toContain("ring-2");
    expect(panelFrameStyles.sourceCollectionFocusedPanel).not.toContain("grid-cols");
    expect(panelFrameStyles.sourceCollectionFocusedPanel).not.toMatch(/(?:^|\s)grid(?:\s|$)/);
    expect(panelFrameStyles.sourceCollectionFocusedPanel).not.toContain("auto-rows");
  });

  it("renders one source-review list and integrates extraction recovery into the stage header", () => {
    expect(activeStageSource).not.toContain("renderCandidatePanel");
    expect(activeStageSource.match(/renderScreeningPanel\(\)/g)).toHaveLength(1);
    expect(activeStageSource).toContain("renderIntegratedRecovery?: () => ReactNode");
    expect(activeStageSource).toContain("sourceCollectionStageIntegratedRecovery");
    expect(activeStageSource).not.toContain("renderRecoveryPanel");
    expect(activeStageStyles.sourceCollectionExtractionPanels).toContain(
      "grid-rows-[minmax(0,1fr)]",
    );
    expect(activeStageStyles.sourceCollectionExtractionPanels).toContain("overflow-hidden");
    expect(activeStageStyles.sourceCollectionExtractionScrollRegion).toContain("overflow-auto");
    expect(activeStageStyles.sourceCollectionExtractionScrollRegion).not.toContain(
      "max-[1020px]:overflow-visible",
    );
    expect(activeStageStyles.sourceCollectionStageIntegratedRecovery).toContain(
      "max-h-[min(48dvh,360px)]",
    );
    expect(activeStageStyles.sourceCollectionStageIntegratedRecovery).toContain("overflow-auto");
  });
});
