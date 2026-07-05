import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

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
    expect(controlsSource).toContain("controlsShellClass");
    expect(controlsSource).toContain("flowRegionClass");
    expect(controlsSource).toContain("modeRegionClass");
    expect(tabsStylesSource).toContain("inline-grid");
    expect(tabsStylesSource).toContain("w-fit");
    expect(tabsStylesSource).toContain("grid-cols-[repeat(4,minmax(132px,168px))]");
    expect(tabsStylesSource).toContain("max-w-full");
    expect(tabsStylesSource).not.toContain("grid-cols-[repeat(4,minmax(118px,1fr))]");
    expect(tabsStylesSource).not.toContain("flex-[1_1_auto]");
    expect(tabsStylesSource).not.toContain("max-w-none");
    expect(tabsStylesSource).not.toContain("grid-cols-[repeat(4,minmax(132px,1fr))]");
    expect(tabsStylesSource).not.toContain("flex-[0_1_620px]");
    expect(tabsStylesSource).not.toContain("max-w-[680px]");
    expect(tabsSource).toContain("stepHintClass");
    expect(tabsSource).not.toContain("segmentButton");
  });

  it("keeps the supervised flow content-sized while mode buttons stay compact", () => {
    expect(controlsStylesSource).toContain("controlsShellClass");
    expect(controlsStylesSource).toContain("grid-cols-[minmax(0,max-content)_auto]");
    expect(controlsStylesSource).toContain("w-fit");
    expect(controlsStylesSource).toContain("max-w-full");
    expect(controlsStylesSource).not.toContain("min-w-0 w-full grid-cols-[minmax(0,1fr)_auto]");
    expect(controlsStylesSource).toContain("justify-self-end");
    expect(controlsStylesSource).toContain("max-w-full");
    expect(tabsStylesSource).not.toContain("grid w-full min-w-0 flex-[1_1_auto]");
    expect(tabsStylesSource).toContain("w-fit");
    expect(tabsStylesSource).toContain("min-w-0");
    expect(tabsStylesSource).toContain("grid-cols-[repeat(4,minmax(132px,168px))]");
    expect(tabsStylesSource).toContain("h-[34px]");
    expect(tabsStylesSource).toContain("h-5 w-5");
    expect(tabsStylesSource).toContain("min-w-6");
    expect(tabsStylesSource).toContain("hidden overflow-hidden");
    expect(tabsStylesSource).toContain("max-[1120px]:grid-cols-[repeat(4,minmax(112px,150px))]");
    expect(tabsSource).not.toContain("repeat(2");
    expect(controlsStylesSource).toContain("min-h-[34px]");
    expect(controlsStylesSource).toContain("min-h-[26px]");
    expect(controlsStylesSource).toContain("flowRegionClass");
    expect(tabsStylesSource).toContain("min-w-0");
  });

  it("keeps workflow tabs from expanding into tall VButton cards", () => {
    expect(tabsStylesSource).toContain("!inline-grid");
    expect(tabsStylesSource).toContain("h-[34px]");
    expect(tabsStylesSource).toContain("max-h-[34px]");
    expect(tabsStylesSource).not.toContain("min-h-[36px]");
    expect(tabsStylesSource).not.toContain("stepMetaClass = \"flex");
    expect(tabsStylesSource).toContain("stepMetaClass = \"sr-only");
    expect(tabsSource).toContain("const tabDescription");
    expect(tabsSource).toContain("aria-label={tabDescription}");
    expect(tabsSource).toContain("title={tabDescription}");
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
