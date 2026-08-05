import { describe, expect, it } from "vitest";

import { sourceCollectionLoadingChrome } from "./actionChrome";
import { buildSourceCollectionActionReadinessBag } from "./presentationActionReadiness";

describe("presentationActionReadiness (F3)", () => {
  it("disables search when no team/run and labels screening idle", () => {
    const reasons = sourceCollectionLoadingChrome("zh");
    const bag = buildSourceCollectionActionReadinessBag({
      lang: "zh",
      reasons,
      loadingText: reasons.loadingText,
      hasTeam: false,
      hasRun: false,
      actionRunId: "",
      canExecuteSearch: false,
      canStart: false,
      canBuildGraph: false,
      assignmentsDataLoading: false,
      recordsDataLoading: false,
      primaryDataLoading: false,
      sourceQualityLoading: false,
      graphDataLoading: false,
      knowledgeIngestionDataLoading: false,
      actionInitialDataPending: false,
      actionDataError: false,
      sourceQualityDataError: false,
      graphDataError: false,
      knowledgeIngestionDataError: false,
      rawRecordCount: 0,
      displayedCandidateCount: 0,
      runPendingScreeningCount: 0,
      runPendingScreeningCountText: "0",
      pendingCandidateImportCount: 0,
      searchOpenAssignmentCount: 0,
      ingestCandidateCount: 0,
      precheckCandidateCount: 0,
      runApprovedCount: 0,
      acceptedBackgroundActive: false,
      operationFailed: false,
      extractionNeedsAgentMaterial: false,
      searchPending: false,
      extractPending: false,
      sourceQualityPending: false,
      graphPending: false,
      knowledgeIngestPending: false,
      startRunPending: false,
      knowledgeCompletedForSelectedRun: false,
    });
    expect(bag.searchActionReadiness.disabled).toBe(true);
    expect(bag.screeningStatusText).toBe("暂无候选");
    expect(bag.loopStartsNewRun).toBe(true);
    expect(bag.candidateExtractionButtonText).toContain("提炼");
  });
});
