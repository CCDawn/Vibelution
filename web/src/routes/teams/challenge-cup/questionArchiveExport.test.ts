import { describe, expect, it } from "vitest";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import type {
  HypothesisRoundListResponse,
  HypothesisRoundRecord,
} from "../../../api/types/hypothesisFirst";
import {
  buildQuestionArchiveHtml,
  exportQuestionArchivePage,
  questionArchiveFileName,
} from "./questionArchiveExport";

const LONG_TEXT = `${"很长的机制描述。".repeat(60)}END`;

function detail(): ChallengeQuestionRunDetailPayload {
  const gate = { required: true as const, decision: "approved" as const, rationale: "人工确认边界清晰。", reviewer: "operator", decided_at: "2026-07-23T00:00:00Z" };
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
      question_en: `How does the brain retrieve memories & "keep" them?`,
      question_zh: "大脑如何提取并<保持>记忆？",
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
      evidence: [
        {
          evidence_id: "E1",
          title: "<script>alert(1)</script> Evil & Title",
          source_type: "peer_reviewed_paper",
          source_url: "https://example.org/paper?a=1&b=2",
          doi: "10.1000/xyz",
          retrieved_at: "2026-07-23T00:00:00Z",
          fact: "A registered evidence statement.",
          relation: "supports",
          verification_status: "metadata_checked",
        },
        {
          evidence_id: "E2",
          title: "Unsafe scheme entry",
          source_type: "dataset",
          source_url: "javascript:alert(2)",
          retrieved_at: "2026-07-23T00:00:00Z",
          fact: "Facts with 'single' and \"double\" quotes.",
          relation: "challenges",
          verification_status: "unverified",
          limitations: ["样本量有限"],
        },
      ],
      hypotheses: [
        {
          hypothesis_id: "HYP-1",
          statement: "Hypothesis <one> statement",
          mechanism: LONG_TEXT,
          novelty_basis: "Novel integration",
          falsifiability: "Fails if prediction one fails",
          predictions: ["Prediction one"],
          supporting_evidence_refs: ["E1"],
          challenging_evidence_refs: ["E2"],
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
        rating: dimension === "novelty" ? ("strong" as const) : ("adequate" as const),
        rationale: `${dimension} 有独立支撑。`,
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
        counterevidence_refs: ["E2"],
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
      sha256: "2".repeat(64),
      immutable: true,
    },
  };
}

function round(overrides: Partial<HypothesisRoundRecord> = {}): HypothesisRoundRecord {
  return {
    program: "challenge-cup",
    theme: "memory",
    campaign: "2026",
    question: "SCI-096",
    branch: "main",
    workflow: "hypothesis-first",
    agentId: "review-executor",
    roundId: "round-1",
    mode: "audit",
    scopeHash: "hash-1",
    status: "closed",
    createdAt: "2026-07-23T01:00:00Z",
    closedAt: "2026-07-23T02:00:00Z",
    candidates: [
      {
        candidateId: "HYP-1",
        claim: "Hypothesis one claim",
        rationale: "rationale",
        differenceFromAlternatives: "diff",
        lineageRefs: [],
        scores: { novelty: 4, competitionFit: 3.5, falsifiability: 4, evidenceSupport: 3, feasibility: 4 },
        diagnostics: { replicability: 4, scopeAlignment: 5 },
        dimensionReviews: [{
          dimension: "novelty",
          rating: "strong",
          rationale: "独立评审认为新颖。",
          evidence_refs: ["E1"],
          reviewer: "audit-agent",
        }],
        reviewedBy: "review-executor",
        status: "accepted",
      },
      {
        candidateId: "HYP-2",
        claim: "Hypothesis two claim",
        rationale: "rationale",
        differenceFromAlternatives: "diff",
        lineageRefs: [],
        scores: { novelty: 3, competitionFit: 4, falsifiability: 3, evidenceSupport: 2, feasibility: 3 },
        reviewedBy: "review-executor",
        status: "rejected",
      },
    ],
    pairwiseComparisons: [{
      comparisonId: "cmp-1",
      leftCandidateId: "HYP-1",
      rightCandidateId: "HYP-2",
      reviewerAgentId: "pair-agent",
      outcome: "left",
      justification: "证据更充分",
    }],
    pareto: {
      paretoFrontCandidateIds: ["HYP-1"],
      dominatedCandidateIds: ["HYP-2"],
      analystAgentId: "pareto-agent",
      notes: "HYP-1 在所有维度不劣于 HYP-2。",
    },
    metaReview: {
      metaReviewId: "meta-1",
      reviewerAgentId: "meta-agent",
      recommendationCandidateId: "HYP-1",
      rationale: "综合各维独立得分与两两对比。",
      riskNotes: "跨脑区外推仍待验证。",
      accepted: true,
    },
    lineage: [],
    meetingRefs: [],
    ...overrides,
  };
}

function roundsPayload(rounds: HypothesisRoundRecord[]): HypothesisRoundListResponse {
  return { schemaVersion: 1, teamId: "research-team", roundCount: rounds.length, rounds };
}

const html = () => buildQuestionArchiveHtml(detail(), roundsPayload([round()]), {
  lang: "zh",
  generatedAt: new Date("2026-09-02T10:30:00"),
});

describe("questionArchiveExport escaping", () => {
  it("never lets payload markup or quotes inject into the document", () => {
    const output = html();
    expect(output.startsWith("<!doctype html>")).toBe(true);
    expect(output).toContain("<style>");
    expect(output).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(output).not.toContain("<script>alert(1)");
    expect(output).toContain("How does the brain retrieve memories &amp; &quot;keep&quot; them?");
    expect(output).toContain("大脑如何提取并&lt;保持&gt;记忆？");
    expect(output).toContain("Hypothesis &lt;one&gt; statement");
    expect(output).toContain("paper?a=1&amp;b=2");
    // No scripts, external resources, inline handlers or non-whitelisted hrefs.
    expect(output).not.toMatch(/<script/i);
    expect(output).not.toMatch(/<link/i);
    expect(output).not.toMatch(/\son[a-z]+\s*=/i);
    expect(output).not.toContain('href="javascript:');
    // The javascript: source_url degrades to plain text, the https one stays a link.
    expect(output).toContain('<span class="plain-url">javascript:alert(2)</span>');
    expect(output).toContain('href="https://example.org/paper?a=1&amp;b=2"');
  });
});

describe("questionArchiveExport sections", () => {
  it("renders every research-chain section plus the integrity footer", () => {
    const output = html();
    for (const id of ["understanding", "evidence", "hypotheses", "reviews", "selection", "plan", "feedback", "summary", "rounds"]) {
      expect(output).toContain(`id="${id}"`);
    }
    expect(output).toContain("问题理解");
    expect(output).toContain("证据清单");
    expect(output).toContain("候选假设");
    expect(output).toContain("七维评价");
    expect(output).toContain("假说选择");
    expect(output).toContain("研究计划");
    expect(output).toContain("反馈修正");
    expect(output).toContain("最终总结");
    expect(output).toContain("评审历程");
    // Reused shared label mappings.
    expect(output).toContain(">支持<");
    expect(output).toContain("同行评审论文");
    expect(output).toContain("元数据已核验");
    expect(output).toContain(">新颖性<");
    expect(output).toContain(">强</span>");
    expect(output).toContain("WP-1");
    // Selection marks the winner and carries rejection reasons.
    expect(output).toContain("已选用");
    expect(output).toContain("保留为替代解释。");
    // Long fields fold instead of exploding the page.
    expect(output).toContain("展开全文（共");
    // Integrity footer records the audit chain.
    expect(output).toContain("1".repeat(64));
    expect(output).toContain("2".repeat(64));
    expect(output).toContain("stage1-sci-096-v3.json");
    expect(output).toContain("stage1-sci-096-v3");
    expect(output).toContain("完整性信息（导出时刻快照）");
    expect(output).toContain("导出时刻");
    expect(output).toContain("只读快照");
    expect(output).toContain("2026-09-02 10:30");
  });

  it("truncates oversized collections with an explicit note", () => {
    const payload = detail();
    payload.output.evidence = Array.from({ length: 15 }, (_, index) => ({
      ...payload.output.evidence[0],
      evidence_id: `E-${index}`,
      title: `Evidence ${index}`,
    }));
    const output = buildQuestionArchiveHtml(payload, undefined, { lang: "zh" });
    expect(output).toContain("E-11");
    expect(output).not.toContain("Evidence 14</strong>");
    expect(output).toContain("已截断：共 15 条，仅展示前 12 条");
  });
});

describe("questionArchiveExport review rounds", () => {
  it("renders per-question rounds with independent scores, Pareto and MetaReview", () => {
    const output = html();
    expect(output).toContain("round-1");
    expect(output).toContain("HYP-2");
    expect(output).toContain("Pareto 前沿");
    expect(output).toContain("MetaReview");
    expect(output).toContain("已采纳");
    expect(output).toContain("评审执行器不产出总分");
    // Uppercase-insensitive question filter keeps foreign-scope rounds out.
    expect(output).not.toContain("round-other");
  });

  it("filters rounds by question scope case-insensitively", () => {
    const payload = roundsPayload([
      round({ roundId: "round-other", question: "SCI-999" }),
      round({ roundId: "round-mine", question: " sci-096 " }),
    ]);
    const output = buildQuestionArchiveHtml(detail(), payload, { lang: "zh" });
    expect(output).toContain("round-mine");
    expect(output).not.toContain("round-other");
  });

  it("falls back to the team ledger only when no round carries a question scope", () => {
    const unscoped = roundsPayload([round({ question: "", roundId: "round-team" })]);
    const fallbackOutput = buildQuestionArchiveHtml(detail(), unscoped, { lang: "zh" });
    expect(fallbackOutput).toContain("round-team");
    expect(fallbackOutput).toContain("轮次台账未携带题目归属字段");

    const foreignOnly = roundsPayload([round({ question: "SCI-999", roundId: "round-x" })]);
    const emptyOutput = buildQuestionArchiveHtml(detail(), foreignOnly, { lang: "zh" });
    expect(emptyOutput).toContain("未找到与本题关联的评审轮次记录");
  });

  it("degrades visibly when the ledger is unavailable and truncates long ledgers", () => {
    const unavailable = buildQuestionArchiveHtml(detail(), undefined, { lang: "zh" });
    expect(unavailable).toContain("评审历程不可用");

    const many = roundsPayload(Array.from({ length: 8 }, (_, index) =>
      round({ roundId: `round-${index}` })));
    const truncated = buildQuestionArchiveHtml(detail(), many, { lang: "zh" });
    expect(truncated).toContain("round-5");
    expect(truncated).not.toContain("round-6</h3>");
    expect(truncated).toContain("已截断：共 8 条，仅展示前 6 条");
  });
});

describe("questionArchiveFileName", () => {
  it("formats challenge-<id>-<yyyyMMdd-HHmm>.html with a sanitized id", () => {
    expect(questionArchiveFileName("SCI-096", new Date(2026, 8, 2, 10, 30)))
      .toBe("challenge-SCI-096-20260902-1030.html");
    expect(questionArchiveFileName("A/B:C D", new Date(2026, 8, 2, 10, 30)))
      .toBe("challenge-A-B-C-D-20260902-1030.html");
    expect(questionArchiveFileName("  ", new Date(2026, 8, 2, 10, 30)))
      .toBe("challenge-question-20260902-1030.html");
  });
});

describe("exportQuestionArchivePage", () => {
  const generatedAt = new Date(2026, 8, 2, 10, 30);

  it("fetches rounds, builds the document and downloads it", async () => {
    const downloads: Array<{ filename: string; html: string }> = [];
    const result = await exportQuestionArchivePage({
      detail: detail(),
      lang: "zh",
      fetchRounds: async (teamId) => {
        expect(teamId).toBe("research-team");
        return roundsPayload([round()]);
      },
      download: (filename, html) => downloads.push({ filename, html }),
      now: () => generatedAt,
    });
    expect(result).toEqual({ filename: "challenge-SCI-096-20260902-1030.html", roundsAvailable: true });
    expect(downloads).toHaveLength(1);
    expect(downloads[0].html).toContain("评审历程");
    expect(downloads[0].html).toContain("round-1");
    expect(downloads[0].html.startsWith("<!doctype html>")).toBe(true);
  });

  it("still exports when the round ledger fetch fails", async () => {
    const downloads: Array<{ filename: string; html: string }> = [];
    const result = await exportQuestionArchivePage({
      detail: detail(),
      fetchRounds: async () => {
        throw new Error("network down");
      },
      download: (filename, html) => downloads.push({ filename, html }),
      now: () => generatedAt,
    });
    expect(result.roundsAvailable).toBe(false);
    expect(downloads).toHaveLength(1);
    expect(downloads[0].html).toContain("评审历程不可用");
  });

  it("exports without any ledger fetch when no team is resolvable", async () => {
    const payload = detail();
    payload.teamId = "";
    const downloads: Array<{ filename: string; html: string }> = [];
    let fetchCalls = 0;
    const result = await exportQuestionArchivePage({
      detail: payload,
      fetchRounds: async () => {
        fetchCalls += 1;
        return roundsPayload([]);
      },
      download: (filename, html) => downloads.push({ filename, html }),
      now: () => generatedAt,
    });
    expect(fetchCalls).toBe(0);
    expect(result.roundsAvailable).toBe(false);
    expect(downloads).toHaveLength(1);
    expect(downloads[0].html).toContain("评审历程不可用");
  });
});
