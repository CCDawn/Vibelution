import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import { getEffectiveIntakeMode } from "./SupervisedWorkspaceControls";

const tabsSource = readFileSync(new URL("./SupervisedWorkspaceTabs.tsx", import.meta.url), "utf-8");
const tabsStylesSource = readFileSync(new URL("./SupervisedWorkspaceTabs.module.css", import.meta.url), "utf-8");
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
    expect(tabsSource).toContain("summaries[view.key]");
    expect(tabsSource).toContain("stepIndex");
    expect(tabsSource).toContain("stepMeta");
    expect(tabsSource).toContain("stepCount");
    expect(tabsSource).toContain("supervisedFlowLabel");
    expect(tabsSource).toContain("supervisedFlowHint");
    expect(tabsSource).toContain("styles.stepHint");
    expect(dictionarySource).toContain("启动与现场");
    expect(dictionarySource).toContain("运行结果");
    expect(dictionarySource).toContain("改进提案");
    expect(dictionarySource).toContain("样本评审");
    expect(tabsStylesSource).toContain(".flowTabs");
    expect(tabsStylesSource).toContain("grid-template-columns: repeat(4");
    expect(tabsStylesSource).toContain(".stepHint");
    expect(tabsStylesSource).not.toContain(".segmentButton");
  });

  it("feeds live run, history, library, and review counts into the supervised flow tabs", () => {
    expect(evolutionRouteSource).toContain("supervisedTabSummaries");
    expect(evolutionRouteSource).toContain("monitoredControlSummary?.stageLabel");
    expect(evolutionRouteSource).toContain("pendingItems.length + libraryItems.length");
    expect(evolutionRouteSource).toContain("highlightedReviewPending");
    expect(evolutionRouteSource).toContain("tabSummaries={supervisedTabSummaries}");
  });
});
