import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import evolutionStyles from "./EvolutionRoute.styles";
import { getEffectiveIntakeMode } from "./SupervisedWorkspaceControls";

const controlsSource = readFileSync(new URL("./SupervisedWorkspaceControls.tsx", import.meta.url), "utf-8");
const controlsStylesSource = readFileSync(new URL("./SupervisedWorkspaceControls.styles.ts", import.meta.url), "utf-8");
const tabsSource = readFileSync(new URL("./SupervisedWorkspaceTabs.tsx", import.meta.url), "utf-8");
const tabsStylesSource = readFileSync(new URL("./SupervisedWorkspaceTabs.styles.ts", import.meta.url), "utf-8");
const evolutionRouteSource = readFileSync(new URL("./EvolutionRoute.tsx", import.meta.url), "utf-8");
const dictionarySource = readFileSync(new URL("../i18n/dictionary.ts", import.meta.url), "utf-8");

describe("supervised workspace controls", () => {
  it("prefers auto when the overview reports auto mode", () => {
    expect(getEffectiveIntakeMode("auto", "manual_review")).toBe("auto");
  });

  it("falls back to config auto mode when overview mode is absent", () => {
    expect(getEffectiveIntakeMode(null, "auto")).toBe("auto");
  });

  it("defaults to manual review when neither source reports auto mode", () => {
    expect(getEffectiveIntakeMode(undefined, undefined)).toBe("manual_review");
  });

  it("renders supervised navigation as a status-bearing flow instead of plain segmented buttons", () => {
    expect(tabsSource).toContain("SupervisedWorkspaceTabSummary");
    expect(tabsSource).toContain("WORKFLOW_STEPS");
    expect(tabsSource).toContain("summaries[step.key]");
    expect(tabsSource).toContain("stepIndex");
    expect(tabsSource).toContain("stepMeta");
    expect(tabsSource).toContain("stepCount");
    expect(tabsSource).toContain("supervisedFlowLabel");
    expect(tabsSource).toContain("supervisedFlowHint");
    expect(tabsSource).toContain("activeWorkflowStepId");
    expect(tabsSource).toContain('key: "baseline_eval"');
    expect(tabsSource).toContain('key: "improve"');
    expect(tabsSource).toContain('key: "rerun_score"');
    expect(tabsSource).toContain('key: "approval"');
    expect(tabsSource).toContain("onWorkflowStepSelect?.(step.key)");
    expect(tabsSource).toContain("role=\"tab\"");
    expect(tabsSource).not.toContain("NavLink");
    expect(tabsSource).not.toContain("href: \"/supervised-evolution/runs\"");
    expect(tabsSource).toContain("stepHintClass");
    expect(dictionarySource).toContain('supervisedFlowLive: "基线评测"');
    expect(dictionarySource).toContain('supervisedFlowRuns: "提出建议与改良"');
    expect(dictionarySource).toContain('supervisedFlowLibrary: "复跑与评分"');
    expect(dictionarySource).toContain('supervisedFlowReview: "用户审批"');
    expect(dictionarySource).not.toContain('supervisedFlowRuns: "运行结果"');
    expect(dictionarySource).not.toContain('supervisedFlowLibrary: "改进提案"');
    expect(dictionarySource).not.toContain('supervisedFlowReview: "样本评审"');
    expect(tabsSource).toContain("flowTabsClass");
    expect(tabsStylesSource).toContain("grid-cols-[repeat(4,minmax(92px,1fr))]");
    expect(tabsSource).toContain("stepHintClass");
    expect(tabsSource).not.toContain("segmentButton");
  });

  it("keeps the supervised flow rail on one dense row before mobile overflow", () => {
    expect(tabsStylesSource).toContain("grid-cols-[repeat(4,minmax(92px,1fr))]");
    expect(tabsStylesSource).toContain("min-h-[38px]");
    expect(tabsStylesSource).toContain("hidden overflow-hidden");
    expect(tabsStylesSource).toContain("max-[1120px]:grid-cols-[repeat(4,minmax(88px,1fr))]");
    expect(tabsSource).not.toContain("repeat(2");
    expect(controlsStylesSource).toContain("min-h-[34px]");
    expect(controlsStylesSource).toContain("min-h-[26px]");
    expect(evolutionStyles.supervisedFlowShell).toContain("min-w-0");
    expect(evolutionStyles.supervisedFlowTabs).toContain("min-w-0");
  });

  it("feeds workflow step summaries into the supervised flow tabs", () => {
    expect(evolutionRouteSource).toContain("supervisedTabSummaries");
    expect(evolutionRouteSource).toContain("supervisedWorkflowTabSummary");
    expect(evolutionRouteSource).toContain("supervisedWorkflowCards[0]");
    expect(evolutionRouteSource).toContain("supervisedWorkflowCards[1]");
    expect(evolutionRouteSource).toContain("supervisedWorkflowCards[2]");
    expect(evolutionRouteSource).toContain("supervisedWorkflowCards[3]");
    expect(evolutionRouteSource).toContain("handleSupervisedWorkflowStepSelect");
    expect(evolutionRouteSource).toContain("activeWorkflowStepId={supervisedSelectedWorkflowStepId}");
    expect(evolutionRouteSource).toContain("onWorkflowStepSelect={handleSupervisedWorkflowStepSelect}");
    expect(evolutionRouteSource).toContain("tabSummaries={supervisedTabSummaries}");
  });
});
