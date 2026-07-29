import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { TeamSourceCollectionExtractionRecoveryWorkspacePanel } from "./TeamSourceCollectionExtractionRecoveryWorkspacePanel";
import type { SourceCollectionStageCardProjection } from "./teams/source-collection/stageProjection";

function projectionWithClosure(input: {
  blockedCount?: number;
  failedCount?: number;
  missingEvidenceAnchorCount?: number;
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
      materializedContentExtraction: input.missingEvidenceAnchorCount === undefined
        ? undefined
        : { missingEvidenceAnchorCount: input.missingEvidenceAnchorCount },
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
  it("uses the materialized evidence gap count instead of source-verification blockers", () => {
    const markup = renderRecoveryPanel(projectionWithClosure({
      blockedCount: 2,
      missingEvidenceAnchorCount: 14,
    }));

    expect(markup).toContain("证据补全");
    expect(markup).toContain("待补证据");
    expect(markup).toContain("14/14");
    expect(markup).not.toContain("2/14");
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

  it("separates source verification from missing evidence anchors", () => {
    const markup = renderRecoveryPanel(projectionWithClosure({
      blockedCount: 2,
      missingEvidenceAnchorCount: 0,
    }));

    expect(markup).toContain("来源核验");
    expect(markup).toContain("提炼完成，待核验来源");
    expect(markup).toContain("待核验来源");
    expect(markup).toContain("2/14");
    expect(markup).toContain("不代表缺少证据锚点");
    expect(markup).not.toContain("待补证据");
    expect(markup).not.toContain("证据补全");
  });
});
