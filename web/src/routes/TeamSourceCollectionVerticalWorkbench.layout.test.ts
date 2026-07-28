import { describe, expect, it } from "vitest";

import persistedHeightListShellSource from "../components/layout/PersistedHeightListShell.tsx?raw";
import activeStageSource from "./TeamSourceCollectionActiveStagePanel.tsx?raw";
import activeStageStyles from "./TeamSourceCollectionActiveStagePanel.styles";
import candidatePanelSource from "./TeamSourceCollectionCandidatePanel.tsx?raw";
import candidatePanelStyles from "./TeamSourceCollectionCandidatePanel.styles";
import screeningPanelSource from "./TeamSourceCollectionScreeningPanel.tsx?raw";
import screeningPanelStyles from "./TeamSourceCollectionScreeningPanel.styles";
import standaloneStageSource from "./TeamSourceCollectionStandaloneStagePanel.tsx?raw";
import standaloneStageStyles from "./TeamSourceCollectionStandaloneStagePanel.styles";
import { SOURCE_COLLECTION_RESULT_PAGE_SIZE } from "./teams/source-collection/presentationModel";

describe("source collection vertical three-column workbench", () => {
  it("places run context, result workspace, and stage controls in persistent desktop rails", () => {
    expect(standaloneStageStyles.sourceCollectionPageBody).toContain(
      "grid-cols-[clamp(300px,20vw,348px)_minmax(520px,1fr)_clamp(270px,17vw,338px)]",
    );
    expect(standaloneStageStyles.sourceCollectionLeftRail).toContain("col-start-1");
    expect(standaloneStageStyles.sourceCollectionPageGrid).toContain("col-start-2 col-span-2");
    expect(activeStageStyles.sourceCollectionStageWorkspace).toContain(
      "grid-cols-[minmax(0,1fr)_clamp(270px,17vw,338px)]",
    );
    expect(activeStageStyles.sourceCollectionStageResult).toContain(
      "col-start-1 row-start-1 row-span-2",
    );
    expect(activeStageStyles.sourceCollectionStageWorkspaceHeader).toContain(
      "col-start-2 row-start-1",
    );
  });

  it("keeps stage navigation free of duplicated long action buttons", () => {
    expect(standaloneStageSource).not.toContain("actions={");
    expect(standaloneStageSource).not.toContain('from "../components/vui"');
  });

  it("groups errors and results into explicit grid surfaces", () => {
    expect(activeStageSource).toContain("sourceCollectionStageErrors");
    expect(activeStageSource).toContain("sourceCollectionStageResult");
    expect(activeStageStyles.sourceCollectionStageChatActions).toContain(
      "grid-cols-[repeat(2,minmax(0,1fr))]",
    );
  });

  it("uses the available extraction workspace before paginating source material", () => {
    expect(SOURCE_COLLECTION_RESULT_PAGE_SIZE).toBe(16);
    expect(activeStageStyles.sourceCollectionExtractionPanels).toContain("h-full");
    expect(activeStageStyles.sourceCollectionExtractionPanels).toContain("overflow-auto");
    expect(activeStageStyles.sourceCollectionExtractionPanels).toContain("flex-col");
    expect(candidatePanelStyles.sourceCollectionExpandedContentPanel).toContain("overflow-visible");
    expect(screeningPanelStyles.sourceCollectionExpandedContentPanel).toContain("overflow-visible");
    expect(candidatePanelStyles.sourceCollectionCandidateListShell).toContain("self-start");
    expect(screeningPanelStyles.sourceCollectionScreeningListShell).toContain("self-start");
    expect(candidatePanelSource).toContain("expandToContent");
    expect(screeningPanelSource).toContain("expandToContent");
    expect(persistedHeightListShellSource).toContain("expandToContent");
    expect(persistedHeightListShellSource).toContain('height: "auto"');
    expect(persistedHeightListShellSource).toContain("expandToContent ? null");
  });
});
