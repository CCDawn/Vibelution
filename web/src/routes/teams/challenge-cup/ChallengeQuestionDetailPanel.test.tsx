import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { ChallengeQuestionDetailPanel } from "./ChallengeQuestionDetailPanel";
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

function detail(): ChallengeQuestionRunDetailPayload {
  const gate = { required: true as const, decision: "approved" as const, rationale: "人工确认边界清晰。" };
  const dimensions = [
    "evidence_support",
    "factual_accuracy",
    "novelty",
    "falsifiability",
    "plan_feasibility",
    "risk_and_ethics",
    "counterexample_coverage",
  ];
  return {
    teamId: "research-team",
    questionId: "SCI-096",
    selectedRunId: "stage1-sci-096-v3",
    record: {
      recordId: "record-sci-096",
      questionId: "SCI-096",
      runId: "stage1-sci-096-v3",
      status: "approved",
      registeredBy: "challenge-output-api",
    },
    output: {
      schema_version: 1,
      catalog_id: "science-125-questions-2021",
      question_id: "SCI-096",
      question_en: "How does the brain retrieve memories?",
      status: "approved",
      run: {
        run_id: "stage1-sci-096-v3",
        started_at: "2026-07-23T00:00:00Z",
        completed_at: "2026-07-23T00:10:00Z",
        model_provider: "dashscope",
        model_id: "dashscope_main/qwen3.6-plus",
        platform: "aliyun_bailian",
        invocation_evidence_refs: ["call-1"],
      },
      problem_understanding: {
        scope: "只讨论可证伪的记忆提取机制。",
        subquestions: ["何种线索触发提取？"],
        assumptions: ["观测数据有效。"],
        known_unknowns: ["跨脑区时序未知。"],
        human_gate: gate,
      },
      evidence: [{
        evidence_id: "E1",
        title: "A real paper title",
        source_type: "peer_reviewed_paper",
        source_url: "https://example.org/paper",
        retrieved_at: "2026-07-23T00:00:00Z",
        fact: "A registered evidence statement.",
        relation: "supports",
        verification_status: "metadata_checked",
      }],
      hypotheses: [
        {
          hypothesis_id: "HYP-1",
          statement: "Hypothesis one",
          mechanism: "Mechanism one",
          novelty_basis: "Novel integration",
          falsifiability: "Fails if prediction one fails",
          predictions: ["Prediction one"],
          supporting_evidence_refs: ["E1"],
          challenging_evidence_refs: [],
          boundary_conditions: ["Boundary one"],
        },
        {
          hypothesis_id: "HYP-2",
          statement: "Hypothesis two",
          mechanism: "Mechanism two",
          novelty_basis: "Alternative account",
          falsifiability: "Fails if prediction two fails",
          predictions: ["Prediction two"],
          supporting_evidence_refs: ["E1"],
          challenging_evidence_refs: [],
          boundary_conditions: ["Boundary two"],
        },
      ],
      dimension_reviews: ["HYP-1", "HYP-2"].flatMap((hypothesis_id) => dimensions.map((dimension) => ({
        hypothesis_id,
        dimension,
        rating: "adequate" as const,
        rationale: `${dimension} has independent support.`,
        evidence_refs: ["E1"],
        reviewer: "Research Review Agent",
      }))),
      selection: {
        selected_hypothesis_id: "HYP-1",
        comparison_method: "multi_dimension_pareto_plus_human_decision",
        tradeoffs: ["证据强度与新颖性"],
        rejected_hypotheses: [{ hypothesis_id: "HYP-2", reason: "保留为替代解释。" }],
        human_gate: gate,
      },
      research_plan: {
        objective: "区分两个假设",
        method: "预注册对照实验",
        work_packages: [{
          work_package_id: "WP-1",
          goal: "准备数据",
          inputs: ["数据"],
          procedure: ["无泄漏预处理"],
          outputs: ["版本化数据集"],
          dependencies: [],
        }],
        variables: ["线索类型"],
        controls: ["匹配对照"],
        data_and_materials: ["公开数据"],
        analysis: ["交叉验证"],
        success_criteria: ["假设可区分"],
        failure_criteria: ["无法区分"],
        stop_conditions: ["数据失真"],
        resources: ["CPU"],
        timeline: ["第 1 周"],
        risks: ["数据偏移"],
        human_gate: gate,
      },
      feedback_iterations: [{
        round: 1,
        trigger: "人工审核",
        input_refs: ["E1"],
        changes: ["收窄论断边界"],
        unresolved_issues: ["跨脑区外推"],
        human_feedback: "批准修订。",
      }],
      final_summary: {
        answer_boundary: "仍是待验证假设。",
        selected_hypothesis: "Hypothesis one",
        research_plan_summary: "运行预注册对照。",
        key_evidence_refs: ["E1"],
        counterevidence_refs: [],
        limitations: ["数据覆盖有限"],
        next_validation_step: "执行对照。",
      },
      audit: {
        source_catalog_sha256: "0".repeat(64),
        output_sha256: "1".repeat(64),
        schema_validation: "passed",
        citation_validation: "passed",
        human_review_status: "passed",
      },
    },
    runs: [],
    artifact: {
      path: "C:\\data\\SCI-096\\stage1-sci-096-v3.json",
      sha256: "1".repeat(64),
      immutable: true,
    },
  };
}

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
