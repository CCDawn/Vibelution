import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { ChallengeQuestionDetailPanel } from "./ChallengeQuestionDetailPanel";
import detailFixture from "./challengeQuestionDetailFixture";
import detailPanelSource from "./ChallengeQuestionDetailPanel.tsx?raw";
import {
  challengeEvidenceSourceTypeLabel,
  challengeEvidenceVerificationStatusLabel,
  challengeRecordStatusLabel,
} from "./ChallengeQuestionDetailPrimitives";

function renderPanel(ui: React.ReactElement): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>,
  );
}

const detail = detailFixture;

describe("ChallengeQuestionDetailPanel archive export", () => {
  it("offers the single-file artifact page export in the question's more-actions menu", () => {
    expect(detailPanelSource).toContain("export-question-archive");
    expect(detailPanelSource).toContain("导出产物页");
    expect(detailPanelSource).toContain("handleExportArchivePage");
    expect(detailPanelSource).toContain("exportQuestionArchivePage");
    expect(detailPanelSource).toContain("fetchHypothesisRounds");

    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        onClose={() => undefined}
      />,
    );
    expect(markup).toContain('aria-label="本题更多操作"');
  });

  it("exposes a direct export entry on the read-only archive surface", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        readOnlyArchive
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain('data-testid="question-archive-export"');
    expect(markup).toContain("导出产物页");
    // The archive stays free of the acceptance more-actions surface.
    expect(markup).not.toContain("更多操作");
  });
});

describe("ChallengeQuestionDetailPanel reset entry", () => {
  it("keeps the destructive action in this question's header menu", () => {
    expect(detailPanelSource).toContain("本题更多操作");
    expect(detailPanelSource).toContain("重置本题运行");
    expect(detailPanelSource).toContain("ChallengeQuestionRunResetDialog");
  });

  it("keeps the reset entry visible when acceptance artifacts are unavailable", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-004"
        teamId="research-team"
        isLoading={false}
        errorMessage="challenge_question_run_not_found"
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain('aria-label="本题更多操作"');
    expect(markup).toContain("如需从头验收");
    expect(detailPanelSource).toMatch(/if \(errorMessage \|\| !detail\)[\s\S]*questionResetMenu/);
  });
});

describe("ChallengeQuestionDetailPanel", () => {
  it("renders the workflow archive as a summary-first read-only surface", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        teamId="research-team"
        detail={detail()}
        isLoading={false}
        readOnlyArchive
        archiveSummary={{
          selectedHypotheses: 1,
          effectiveReviews: 3,
          retryAttempts: 2,
          collectionRequests: 1,
          reviewHistory: [{
            id: "meeting-3",
            round: 3,
            status: "closed",
            digestAvailable: true,
            retryAttempts: 1,
          }],
        }}
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain('data-testid="question-archive"');
    expect(markup).toContain("题目档案 · 只读");
    expect(markup).toContain("采用假说");
    expect(markup).toContain("有效评审");
    expect(markup).toContain(">3<");
    expect(markup).toContain("失败重试");
    expect(markup).toContain(">2<");
    expect(markup).toContain("资料请求");
    expect(markup).toContain("假说摘要");
    expect(markup).toContain("评审历程");
    expect(markup).toContain("第 3 轮");
    expect(markup).toContain("含 1 次失败重试");
    expect(markup).not.toContain("Pareto 前沿");
    // R4.5: the archive hosts the read-only question lineage section; the
    // heavier acceptance surfaces (full plan/review editing) still must not
    // leak into the summary-first archive.
    expect(markup).toContain('data-testid="question-lineage-section"');
    expect(markup).toContain("全链谱系 · 只读");
    expect(markup.match(/aria-expanded="true"/g)).toHaveLength(1);
    expect(markup).not.toContain("更多操作");
    expect(markup).not.toContain("登记修订产出");
    expect(markup).not.toContain("提交审核结论");
    expect(markup).not.toContain("研究计划");
  });

  it("keeps archive failure compact and returns only to the current task", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-999"
        teamId="research-team"
        isLoading={false}
        errorMessage="challenge_question_run_not_found"
        readOnlyArchive
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain('data-testid="question-archive-error"');
    expect(markup).toContain("返回当前任务");
    expect(markup).not.toContain("返回题目列表");
    expect(markup).not.toContain("question-detail-fail-soft-ops");
    expect(markup).not.toContain("更多操作");
    expect(markup).not.toContain("重置本题运行");
    expect(markup).not.toContain("challenge_question_run_not_found");
  });

  it("renders the complete SCI-096 white-box audit chain without inventing missing anchors", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain("SCI-096");
    expect(markup).toContain("证据事实");
    // The schema has no anchor field; the old unconditional warning was removed.
    expect(markup).not.toContain("证据锚点未登记");
    expect(markup).toContain("Hypothesis one");
    expect(markup).toContain("Hypothesis two");
    expect(markup).toContain("收窄论断边界");
    expect(markup).toContain("stage1-sci-096-v3.json");
    expect(markup).not.toContain("SCI-098");
    expect(markup).not.toContain("各维度独立呈现，不汇总成单一总分");
  });

  it("shows a read-only review summary once the record is approved", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain('data-vui="question-review-summary"');
    expect(markup).toContain("已正式批准");
    expect(markup).not.toContain("提交审核结论");
  });

  it("renders the H1-H4 review form while the record awaits approval", () => {
    const pending = detail();
    pending.record = { ...pending.record, status: "pending_review" };
    const gate = { required: true as const, decision: "pending" as const, rationale: "" };
    pending.output = {
      ...pending.output,
      problem_understanding: { ...pending.output.problem_understanding, human_gate: gate },
      selection: { ...pending.output.selection, human_gate: gate },
      research_plan: { ...pending.output.research_plan, human_gate: gate },
      audit: { ...pending.output.audit, human_review_status: "pending" },
    };
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={pending}
        isLoading={false}
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain('data-vui="question-review-form"');
    expect(markup).toContain("H1 问题理解");
    expect(markup).toContain("H4 外部产出");
    expect(markup).toContain("提交审核结论");
    expect(markup).toContain("审核人");
    expect(markup).toContain("审核意见");
  });

  it("offers revision registration only while the record needs revision", () => {
    const revision = detail();
    revision.record = { ...revision.record, status: "needs_revision" };
    const revisionMarkup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={revision}
        isLoading={false}
        onClose={() => undefined}
      />,
    );
    expect(revisionMarkup).toContain("登记修订产出");

    const approvedMarkup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        onClose={() => undefined}
      />,
    );
    expect(approvedMarkup).not.toContain("登记修订产出");
  });

  it("keeps review operations usable behind a local acceptance-archive warning", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-999"
        teamId="research-team"
        isLoading={false}
        errorMessage="challenge_question_run_not_found"
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain("SCI-999");
    expect(markup).toContain('data-testid="question-detail-fail-soft-warning"');
    expect(markup).toContain('data-vui="error-summary"');
    expect(markup).toContain('data-tone="warning"');
    expect(markup).toContain('role="status"');
    expect(markup).toContain("验收档案暂不可用，假说评审仍可继续");
    expect(markup).toContain("返回题目列表");
    expect(markup).toContain("question-detail-fail-soft-ops");
    expect(markup).toContain("正在读取假说选择上下文");
    expect(markup).toContain("正在解析讨论入口");
    expect(markup).not.toContain("审核工件不可用");
    expect(markup).not.toContain("操作未完成");
    expect(markup).not.toContain("当前研究项目或其他题目的资料");
  });

  it("productizes the load error and keeps the raw message in collapsible technical details", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-999"
        isLoading={false}
        errorMessage="challenge_question_run_not_found"
        onClose={() => undefined}
      />,
    );

    // Productized copy leads; the raw backend message only survives inside
    // the collapsed technical-details block.
    expect(markup).toContain("SCI-999 的验收档案暂不可用");
    expect(markup).toContain("技术细节");
    expect(markup).toContain("<details");
    expect(markup).toContain("challenge_question_run_not_found");
    expect(markup).not.toContain("question-detail-fail-soft-ops");
    expect(markup).not.toContain("假说评审仍可继续");
  });

  it("maps the record status enum to Chinese labels", () => {
    const pending = detail();
    pending.record = { ...pending.record, status: "pending_review" };
    const pendingMarkup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={pending}
        isLoading={false}
        onClose={() => undefined}
      />,
    );
    expect(pendingMarkup).toContain("待审核");
    expect(pendingMarkup).not.toContain(">pending_review<");

    const revision = detail();
    revision.record = { ...revision.record, status: "needs_revision" };
    const revisionMarkup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={revision}
        isLoading={false}
        onClose={() => undefined}
      />,
    );
    expect(revisionMarkup).toContain("需修改");
    expect(revisionMarkup).not.toContain(">needs_revision<");
  });

  it("maps the evidence relation enum to Chinese labels", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain(">支持<");
    expect(markup).not.toContain(">supports<");
    expect(markup).toContain("同行评审论文");
    expect(markup).toContain("元数据已核验");
    expect(markup).not.toContain("peer_reviewed_paper");
    expect(markup).not.toContain("metadata_checked");
  });

  it("keeps the shared challenge labels bilingual", () => {
    expect(challengeRecordStatusLabel("review_required", "zh")).toBe("待审核");
    expect(challengeRecordStatusLabel("review_required", "en")).toBe("Pending review");
    expect(challengeEvidenceSourceTypeLabel("peer_reviewed_paper", "zh")).toBe("同行评审论文");
    expect(challengeEvidenceSourceTypeLabel("peer_reviewed_paper", "en")).toBe("Peer-reviewed paper");
    expect(challengeEvidenceVerificationStatusLabel("metadata_checked", "zh")).toBe("元数据已核验");
    expect(challengeEvidenceVerificationStatusLabel("metadata_checked", "en")).toBe("Metadata checked");
  });

  it("keeps the artifact path and SHA-256 inside collapsible technical details", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        onClose={() => undefined}
      />,
    );

    const artifactSection = markup.split('id="artifact"')[1] ?? "";
    expect(artifactSection).toContain("技术细节");
    expect(artifactSection).toContain("<details");
    expect(artifactSection).toContain("stage1-sci-096-v3.json");
    expect(artifactSection).toContain("SHA256");
  });

  it("keeps section headings as the only numbered source for the anchor navigation", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        onClose={() => undefined}
      />,
    );
    const nav = markup.match(/<nav[^>]*aria-label="单题验收章节"[\s\S]*?<\/nav>/)?.[0] || "";

    expect(nav).toContain("题目与接单");
    expect(nav).toContain("最终工件");
    expect(nav).not.toMatch(/<span>\d+<\/span>/);
    expect(markup).toContain(">01</span>");
    expect(markup).toContain(">08</span>");
  });
});

describe("ChallengeQuestionDetailPanel stage zones", () => {
  function renderAcceptance(overrides?: {
    recordStatus?: string;
    gateDecision?: "pending" | "approved" | "revision_requested" | "rejected";
    withoutPlan?: boolean;
  }): string {
    const base = detail();
    const payload: ChallengeQuestionRunDetailPayload = {
      ...base,
      record: { ...base.record, status: overrides?.recordStatus ?? base.record.status },
      output: {
        ...base.output,
        selection: {
          ...base.output.selection,
          human_gate: {
            ...base.output.selection.human_gate,
            decision: overrides?.gateDecision ?? base.output.selection.human_gate.decision,
          },
        },
        research_plan: overrides?.withoutPlan
          ? {
            ...base.output.research_plan,
            objective: "",
            method: "",
            work_packages: [],
          }
          : base.output.research_plan,
      },
    };
    return renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={payload}
        isLoading={false}
        onClose={() => undefined}
      />,
    );
  }

  it("splits the anchor directory into the two descriptive stage zones", () => {
    const markup = renderAcceptance();
    const nav = markup.match(/<nav[^>]*aria-label="单题验收章节"[\s\S]*?<\/nav>/)?.[0] || "";

    expect(nav).toContain("假说生成");
    expect(nav).toContain("研究计划与实验 · 未激活");
    // Descriptive zone names, never stage ordinals.
    expect(nav).not.toContain("第一阶段");
    expect(nav).not.toContain("第二阶段");
    // Hypothesis artifacts live in zone one; plan artifacts in zone two.
    const hypothesisGroup = nav.match(/data-stage-zone="hypothesis"[\s\S]*?<\/div>/)?.[0] || "";
    const planGroup = nav.match(/data-stage-zone="plan"[\s\S]*?<\/div>/)?.[0] || "";
    expect(hypothesisGroup).toContain("候选假设");
    expect(hypothesisGroup).toContain("评审轮次");
    expect(hypothesisGroup).not.toContain("研究计划");
    expect(planGroup).toContain("研究计划");
    expect(planGroup).toContain("最终工件");
    expect(planGroup).not.toContain("候选假设");
  });

  it("marks the hypothesis zone settled for an approved stage-one record", () => {
    const markup = renderAcceptance({ recordStatus: "approved", gateDecision: "pending" });
    expect(markup).toContain('data-testid="question-stage-zone-hypothesis"');
    expect(markup).toContain("假说已定");
    expect(markup).not.toContain("假说生成中");
  });

  it("marks the hypothesis zone generating while the stage-one gate is open", () => {
    const markup = renderAcceptance({ recordStatus: "pending_review", gateDecision: "pending" });
    expect(markup).toContain("假说生成中");
    expect(markup).not.toContain("假说已定");
  });

  it("keeps the plan zone permanently inactive with the activation hint", () => {
    const markup = renderAcceptance();
    expect(markup).toContain('data-testid="question-stage-zone-plan"');
    expect(markup).toContain("未激活");
    expect(markup).toContain("需按题显式开启");
    // No stage-two activation entry point anywhere on the page.
    expect(markup).not.toContain("激活第二阶段");
    expect(markup).not.toContain("开启第二阶段");
  });

  it("flags an existing plan artifact as proposal-only pre-projection", () => {
    const markup = renderAcceptance();
    expect(markup).toContain('data-testid="question-plan-proposal-tag"');
    expect(markup).toContain("预投影（proposal only）");
    expect(markup).not.toContain('data-testid="question-plan-inactive-empty"');
  });

  it("shows the inactive empty note when the run output carries no plan", () => {
    const markup = renderAcceptance({ withoutPlan: true });
    expect(markup).toContain('data-testid="question-plan-inactive-empty"');
    expect(markup).not.toContain('data-testid="question-plan-proposal-tag"');
  });

  it("keeps the read-only archive free of stage zone chrome", () => {
    const markup = renderPanel(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        readOnlyArchive
        onClose={() => undefined}
      />,
    );
    expect(markup).not.toContain('data-testid="question-stage-zone-hypothesis"');
    expect(markup).not.toContain('data-testid="question-stage-zone-plan"');
  });
});
