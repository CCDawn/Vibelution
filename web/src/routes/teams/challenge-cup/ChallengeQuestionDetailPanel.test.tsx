import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { ChallengeQuestionDetailPanel } from "./ChallengeQuestionDetailPanel";

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

describe("ChallengeQuestionDetailPanel", () => {
  it("renders the complete SCI-096 white-box audit chain without inventing missing anchors", () => {
    const markup = renderToStaticMarkup(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-096"
        detail={detail()}
        isLoading={false}
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain("SCI-096");
    expect(markup).toContain("题目级“接单 Agent”身份尚未写入正式工件");
    expect(markup).toContain("登记的证据事实（非原文摘录）");
    expect(markup).toContain("原文逐字摘录与页码/段落锚点未登记");
    expect(markup).toContain("Hypothesis one");
    expect(markup).toContain("Hypothesis two");
    expect(markup).toContain("各维度独立呈现，不汇总成单一总分");
    expect(markup).toContain("收窄论断边界");
    expect(markup).toContain("stage1-sci-096-v3.json");
    expect(markup).not.toContain("SCI-098");
  });

  it("fails closed when the requested question artifact is unavailable", () => {
    const markup = renderToStaticMarkup(
      <ChallengeQuestionDetailPanel
        requestedQuestionId="SCI-999"
        isLoading={false}
        errorMessage="challenge_question_run_not_found"
        onClose={() => undefined}
      />,
    );

    expect(markup).toContain("SCI-999");
    expect(markup).toContain("不会回退到当前研究项目或其他题目的资料");
  });
});
