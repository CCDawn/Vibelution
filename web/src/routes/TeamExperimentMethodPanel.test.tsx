import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ExperimentContractV2, ExperimentMethodCatalogPayload } from "../api/types";
import {
  TeamExperimentMethodPanel,
  buildExperimentPlanMethodRequest,
  createExperimentMethodFormDraft,
  isExperimentMethodDraftComplete,
  selectExperimentMethod,
} from "./TeamExperimentMethodPanel";
import panelSource from "./TeamExperimentMethodPanel.tsx?raw";
import styles from "./TeamExperimentMethodPanel.styles";

const catalog: ExperimentMethodCatalogPayload = {
  schemaVersion: 2,
  teamId: "research-team",
  researchModes: [
    { modeId: "hypothesis_and_plan", labelZh: "A 假设与计划", labelEn: "A Hypothesis and plan" },
    { modeId: "experiment_feedback", labelZh: "B 实验与反馈", labelEn: "B Experiment and feedback" },
    { modeId: "full_research_loop", labelZh: "A+B 完整闭环", labelEn: "A+B Full research loop" },
  ],
  experimentPurposes: [
    { purposeId: "baseline_comparison", labelZh: "基线比较", labelEn: "Baseline comparison" },
    { purposeId: "robustness", labelZh: "稳健性验证", labelEn: "Robustness" },
  ],
  methods: [
    {
      methodId: "model_training_inference",
      labelZh: "模型训练/推理",
      labelEn: "Model training / inference",
      requiredConfigFields: ["dataset", "model", "baseline", "seeds", "budget", "smokePlan"],
      adapterAvailability: {
        hypothesis_and_plan: { requestedAdapterId: "", resolvedAdapterId: "", resolvedAdapterVersion: "", selectionSource: "unresolved", unavailableReason: "Execution Adapter is not required." },
        experiment_feedback: { requestedAdapterId: "", resolvedAdapterId: "", resolvedAdapterVersion: "", selectionSource: "unresolved", unavailableReason: "No Adapter satisfies required capabilities: full_run." },
        full_research_loop: { requestedAdapterId: "", resolvedAdapterId: "", resolvedAdapterVersion: "", selectionSource: "unresolved", unavailableReason: "No Adapter satisfies required capabilities: full_run." },
      },
    },
    {
      methodId: "numerical_simulation",
      labelZh: "数值仿真",
      labelEn: "Numerical simulation",
      requiredConfigFields: ["simulator", "scenario", "parameters", "replicates"],
      adapterAvailability: {
        hypothesis_and_plan: { requestedAdapterId: "", resolvedAdapterId: "", resolvedAdapterVersion: "", selectionSource: "unresolved", unavailableReason: "Execution Adapter is not required." },
        experiment_feedback: { requestedAdapterId: "", resolvedAdapterId: "", resolvedAdapterVersion: "", selectionSource: "unresolved", unavailableReason: "No available Adapter is registered." },
        full_research_loop: { requestedAdapterId: "", resolvedAdapterId: "", resolvedAdapterVersion: "", selectionSource: "unresolved", unavailableReason: "No available Adapter is registered." },
      },
    },
  ],
  adapters: [
    {
      adapterId: "fashion_mnist_predictive_coding_multi_seed",
      adapterVersion: "1.0.0",
      method: "model_training_inference",
      executionMode: "local_process",
      capabilities: ["validate", "prepare", "smoke", "full_run", "collect"],
      availability: "available",
      unavailableReason: "Requires an explicit local CPU environment.",
      formalResult: true,
      requiresExplicitSelection: true,
      priority: 110,
    },
  ],
  boundaries: {
    methodCatalogSource: "backend_registry",
    environmentProbeRole: "adapter_preflight",
    evidenceReviewRole: "upstream_research_stage",
    llmSelectsAdapterId: false,
  },
};

const simulationContract: ExperimentContractV2 = {
  schemaVersion: 2,
  planId: "exp-plan-sim-v1",
  revision: 1,
  teamId: "research-team",
  researchProfileId: "generic-simulation",
  researchMode: "experiment_feedback",
  purpose: { primaryPurpose: "robustness", secondaryPurposes: [] },
  experimentMethod: "numerical_simulation",
  adapterSelection: { requestedAdapterId: "", resolvedAdapterId: "", resolvedAdapterVersion: "", selectionSource: "unresolved", unavailableReason: "No available Adapter is registered." },
  researchQuestion: "How robust is the policy under scenario changes?",
  objective: "Compare a parameter sweep across scenarios.",
  hypothesisRefs: ["hypothesis-sim-1"],
  evidenceRefs: [],
  methodConfig: {
    simulator: "controllable-agent-simulator",
    scenario: "resource-constrained adaptation",
    parameters: { temperature: [0.1, 0.5, 1] },
    replicates: 5,
  },
  metricContract: {
    primaryMetric: "task_success_rate",
    metrics: [{ name: "task_success_rate", direction: "maximize" }],
  },
  decisionContract: {
    successCriteria: ["success remains above threshold"],
    failureCriteria: ["success falls below threshold"],
    inconclusiveCriteria: ["replicate variance remains too high"],
  },
  status: "draft",
};

describe("TeamExperimentMethodPanel", () => {
  it("renders the three-level selection and model-specific fields from the backend catalog", () => {
    const markup = renderToStaticMarkup(
      <TeamExperimentMethodPanel
        lang="zh"
        catalog={catalog}
        activeContract={null}
        fallbackResearchQuestion="预测编码是否改善基线？"
        loading={false}
        submitting={false}
        canCreatePlan
        onSubmit={() => undefined}
      />,
    );

    expect(markup).toContain('data-experiment-method-panel="true"');
    expect(markup).toContain('data-selected-method="model_training_inference"');
    expect(markup).toContain("A+B 完整闭环");
    expect(markup).toContain("基线比较");
    expect(markup).toContain("模型训练/推理");
    expect(markup).toContain("数值仿真");
    expect(markup).toContain("公平基线");
    expect(markup).toContain("随机种子");
    expect(markup).toContain("执行器尚未就绪");
    expect(markup).toContain("执行器选择");
    expect(markup).toContain("fashion_mnist_predictive_coding_multi_seed");
    expect(markup).toContain("预测编码是否改善基线？");
  });

  it("keeps an explicit adapter selection in the plan request", () => {
    const draft = createExperimentMethodFormDraft(null, "预测编码是否改善基线？");
    draft.requestedAdapterId = "fashion_mnist_predictive_coding_multi_seed";
    draft.methodConfigs.model_training_inference = {
      dataset: "FashionMNIST pinned split",
      model: "shared autoencoder",
      baseline: "one-pass reconstruction",
      seeds: "17, 42, 101",
      budget: "8 epochs per seed",
      smokePlan: "single-seed artifact review before multi-seed full run",
    };
    draft.primaryMetric = "masked reconstruction mse";
    draft.successCriteria = "mean improvement is positive";
    draft.failureCriteria = "mean improvement is negative";
    draft.inconclusiveCriteria = "seed variance is too high";

    const request = buildExperimentPlanMethodRequest(draft, catalog.methods[0]);

    expect(request.requestedAdapterId).toBe("fashion_mnist_predictive_coding_multi_seed");
    expect(request.methodConfig.seeds).toEqual([17, 42, 101]);
  });

  it("restores the active simulation method and renders its dynamic fields", () => {
    const markup = renderToStaticMarkup(
      <TeamExperimentMethodPanel
        lang="zh"
        catalog={catalog}
        activeContract={simulationContract}
        activePlanStatus="draft"
        loading={false}
        submitting={false}
        canCreatePlan
        onSubmit={() => undefined}
      />,
    );

    expect(markup).toContain('data-selected-method="numerical_simulation"');
    expect(markup).toContain("当前计划");
    expect(markup).toContain("仿真器");
    expect(markup).toContain("仿真场景");
    expect(markup).toContain("重复次数");
    expect(markup).toContain("controllable-agent-simulator");
    expect(markup).toContain("保存为新版本");
  });

  it("preserves per-method drafts and builds a versioned typed request", () => {
    const initial = createExperimentMethodFormDraft(simulationContract);
    initial.methodConfigs.model_training_inference = {
      dataset: "FashionMNIST",
      model: "predictive coding candidate",
      baseline: "backprop baseline",
      seeds: "17, 42, 101",
      budget: "20 epochs",
      smokePlan: "one bounded batch",
    };
    initial.researchQuestion = "Does predictive coding improve the benchmark?";
    initial.primaryMetric = "test_accuracy";
    initial.successCriteria = "candidate improves fairly";
    initial.failureCriteria = "candidate is consistently worse";
    initial.inconclusiveCriteria = "seed variance is too high";
    const selected = selectExperimentMethod(initial, "model_training_inference");
    const method = catalog.methods[0];
    const payload = buildExperimentPlanMethodRequest(selected, method, simulationContract);

    expect(selected.methodConfigs.numerical_simulation.simulator).toBe("controllable-agent-simulator");
    expect(isExperimentMethodDraftComplete(selected, method)).toBe(true);
    expect(payload.revision).toBe(2);
    expect(payload.supersedesPlanId).toBe("exp-plan-sim-v1");
    expect(payload.methodConfig.seeds).toEqual([17, 42, 101]);
    expect(payload.experimentMethod).toBe("model_training_inference");
  });

  it("keeps loading geometry stable and exposes keyboard selection state", () => {
    const loadingMarkup = renderToStaticMarkup(
      <TeamExperimentMethodPanel
        lang="zh"
        loading
        submitting={false}
        canCreatePlan={false}
        onSubmit={() => undefined}
      />,
    );

    expect(styles.loading).toContain("min-h-[16rem]");
    expect(styles.form).toContain("min-h-[18rem]");
    expect(loadingMarkup).toContain("读取实验方式");
    expect(panelSource).toContain("aria-pressed={draft.researchMode === mode.modeId}");
    expect(panelSource).toContain("aria-pressed={draft.experimentMethod === method.methodId}");
    expect(panelSource).toContain('aria-live="polite"');
  });
});
