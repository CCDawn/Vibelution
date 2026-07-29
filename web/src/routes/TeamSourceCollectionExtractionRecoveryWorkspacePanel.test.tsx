import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { TeamSourceCollectionExtractionRecoveryWorkspacePanel } from "./TeamSourceCollectionExtractionRecoveryWorkspacePanel";
import type { SourceCollectionStageCardProjection } from "./teams/source-collection/stageProjection";

function projectionWithClosure(input: {
  blockedCount?: number;
  failedCount?: number;
  status?: string;
  userStatus?: string;
}) {
  return {
    status: input.status ?? "partial_current_inputs",
    counts: {
      input: 14,
      output: 14,
      pending: 14,
    },
    latestTask: {
      coverageSummary: {
        applicable: true,
        blocked: input.blockedCount ?? 0,
        complete: true,
        invalid: 0,
        missing: 0,
        processed: 14,
        total: 14,
      },
      closureSummary: {
        blockedCount: input.blockedCount ?? 0,
        failedCount: input.failedCount ?? 0,
        successCount: 14,
        userStatus: input.userStatus ?? "success",
      },
      invalidCandidateIds: [],
      invalidRecordIds: [],
    },
  } as unknown as SourceCollectionStageCardProjection;
}

function renderRecoveryPanel(candidateProjection: SourceCollectionStageCardProjection) {
  return renderToStaticMarkup(
    <TeamSourceCollectionExtractionRecoveryWorkspacePanel
      candidateProjection={candidateProjection}
      lang="zh"
      sourceCollectionRawRecordCount={14}
      sourceCollectionRunApprovedCount={0}
      sourceCollectionDisplayedCandidateCount={14}
      sourceCollectionPrimaryDataLoading={false}
      sourceCollectionLoadingText="加载中"
      sourceCollectionCandidateStepState="pending"
      sourceCollectionExtractionExcludedRecoveryState={{
        blockedByExcludedSources: false,
        tone: "danger",
      }}
      sourceCollectionActionDisabledTitle={() => undefined}
      sourceCollectionStageActionReadinessFor={() => ({ disabled: false })}
      openSourceCollectionStageAgentChat={vi.fn()}
      startSourceCollectionStageSessionTask={vi.fn()}
      runSourceCollectionCandidateExtractionAction={vi.fn()}
      sourceCollectionCandidateExtractionActionReadiness={{ disabled: false }}
      runSourceCollectionScreeningAction={vi.fn()}
      sourceCollectionScreeningActionReadiness={{ disabled: false }}
      sourceCollectionScreeningButtonText="Agent 重新提炼复核"
      sourceCollectionRunPendingScreeningCountText="0"
    />,
  );
}

describe("TeamSourceCollectionExtractionRecoveryWorkspacePanel", () => {
  it("presents completed extraction with evidence gaps as evidence completion, not failure", () => {
    const markup = renderRecoveryPanel(projectionWithClosure({ blockedCount: 2 }));

    expect(markup).toContain("证据补全");
    expect(markup).toContain("待补证据");
    expect(markup).toContain("2/14");
    expect(markup).not.toContain("提炼失败");
  });

  it("preserves failure semantics for a real extraction failure", () => {
    const markup = renderRecoveryPanel(projectionWithClosure({
      failedCount: 1,
      status: "failed",
      userStatus: "failed",
    }));

    expect(markup).toContain("提炼失败恢复");
    expect(markup).toContain("提炼失败");
    expect(markup).toContain("1/14");
  });
});
