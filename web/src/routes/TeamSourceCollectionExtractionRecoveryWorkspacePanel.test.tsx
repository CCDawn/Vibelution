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

function renderRecoveryPanel(
  candidateProjection: SourceCollectionStageCardProjection,
  pendingScreeningCountText = "0",
  candidateStepState = "pending",
) {
  return renderToStaticMarkup(
    <TeamSourceCollectionExtractionRecoveryWorkspacePanel
      candidateProjection={candidateProjection}
      lang="zh"
      sourceCollectionRawRecordCount={14}
      sourceCollectionRunApprovedCount={0}
      sourceCollectionDisplayedCandidateCount={14}
      sourceCollectionPrimaryDataLoading={false}
      sourceCollectionLoadingText="加载中"
      sourceCollectionCandidateStepState={candidateStepState}
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
      sourceCollectionScreeningButtonText="重新质量审查"
      sourceCollectionRunPendingScreeningCountText={pendingScreeningCountText}
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

  it("trusts complete current coverage after a superseded source shrinks the active set", () => {
    const projection = projectionWithClosure({
      blockedCount: 14,
      missingEvidenceAnchorCount: 14,
    });
    projection.currentCoverageSummary = {
      applicable: true,
      blocked: 13,
      complete: true,
      invalid: 0,
      missing: 0,
      processed: 13,
      total: 13,
    };

    const markup = renderRecoveryPanel(projection, "0", "failed");

    expect(markup).toContain("证据补全");
    expect(markup).toContain("提炼完成，待补证据");
    expect(markup).toContain("13/13");
    expect(markup).not.toContain("14/14");
    expect(markup).not.toContain("提炼失败恢复");
    expect(markup).not.toContain("继续 Agent 提炼");
    expect(markup).toContain("要求 Agent 补充证据");
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

  it("treats incomplete coverage without hard failures as continue-progress, not failure", () => {
    const projection = {
      status: "partial_current_inputs",
      counts: { input: 19, output: 0, pending: 19 },
      latestTask: {
        coverageSummary: {
          applicable: true,
          blocked: 0,
          complete: false,
          invalid: 0,
          missing: 19,
          processed: 0,
          total: 19,
        },
        closureSummary: {
          blockedCount: 0,
          failedCount: 0,
          successCount: 0,
          userStatus: "pending",
        },
        invalidCandidateIds: [],
        invalidRecordIds: [],
      },
    } as unknown as SourceCollectionStageCardProjection;

    const markup = renderRecoveryPanel(projection);

    expect(markup).toContain("继续提炼");
    expect(markup).toContain("待补提炼");
    expect(markup).toContain("待处理");
    expect(markup).toContain("不是系统故障");
    expect(markup).toContain("继续 Agent 提炼");
    expect(markup).not.toContain("提炼失败恢复");
    expect(markup).not.toContain("提炼失败");
  });

  it("separates source verification from missing evidence anchors", () => {
    const markup = renderRecoveryPanel(projectionWithClosure({
      blockedCount: 2,
      missingEvidenceAnchorCount: 0,
    }), "10");

    expect(markup).toContain("来源核验");
    expect(markup).toContain("来源核验");
    expect(markup).toContain("提炼完成，待核验来源");
    expect(markup).toContain("待核验来源");
    expect(markup).toContain("2/14");
    expect(markup).toContain("提炼覆盖");
    expect(markup).toContain("进入 Agent 私聊补充材料");
    expect(markup).toContain("需核验版本/可靠性");
    expect(markup).toContain("不等于缺证据锚点");
    expect(markup).toContain("请在私聊补入新的可公开核验材料");
    expect(markup).toContain("重新质量审查");
    expect(markup).toContain("待质量审查");
    expect(markup).toContain("<strong>10</strong>");
    expect(markup).toContain("lucide-circle-check");
    expect(markup).not.toContain("lucide-triangle-alert");
    expect(markup).not.toContain("待补提炼");
    expect(markup).not.toContain("待补证据");
    expect(markup).not.toContain("证据补全");
  });

  it("stageCard presentation omits action buttons so the stage header owns CTAs", () => {
    const markup = renderToStaticMarkup(
      <TeamSourceCollectionExtractionRecoveryWorkspacePanel
        candidateProjection={projectionWithClosure({ blockedCount: 2, missingEvidenceAnchorCount: 0 })}
        lang="zh"
        sourceCollectionRawRecordCount={14}
        sourceCollectionRunApprovedCount={0}
        sourceCollectionDisplayedCandidateCount={14}
        sourceCollectionPrimaryDataLoading={false}
        sourceCollectionLoadingText="加载中"
        sourceCollectionCandidateStepState="pending"
        sourceCollectionExtractionExcludedRecoveryState={{ blockedByExcludedSources: false, tone: "danger" }}
        sourceCollectionActionDisabledTitle={() => undefined}
        sourceCollectionStageActionReadinessFor={() => ({ disabled: false })}
        openSourceCollectionStageAgentChat={vi.fn()}
        startSourceCollectionStageSessionTask={vi.fn()}
        runSourceCollectionCandidateExtractionAction={vi.fn()}
        sourceCollectionCandidateExtractionActionReadiness={{ disabled: false }}
        runSourceCollectionScreeningAction={vi.fn()}
        sourceCollectionScreeningActionReadiness={{ disabled: false }}
        sourceCollectionScreeningButtonText="重新质量审查"
        sourceCollectionRunPendingScreeningCountText="0"
        presentation="stageCard"
        includeChatAction={false}
      />,
    );
    expect(markup).toContain("来源核验");
    expect(markup).toContain("2/14");
    expect(markup).not.toContain("要求 Agent 补充材料");
    expect(markup).not.toContain("进入 Agent 私聊");
    expect(markup).not.toContain("补导入候选");
  });
});
