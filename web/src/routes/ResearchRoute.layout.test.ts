import { describe, expect, it } from "vitest";

import styles from "./ResearchRoute.styles";
import routeSource from "./ResearchRoute.tsx?raw";

const majorResearchSurfaceKeys = [
  "agentModeCard",
  "agentModeCard_live",
  "agentPanel",
  "summaryCard",
  "intakePanel",
  "historyPanel",
  "pipelinePanel",
  "processPanel",
  "stageCard",
  "stageCard_active",
  "stageCard_compact",
  "stageResultSummary",
  "agentTracePanel",
  "agentTracePanel_collapsed",
  "agentTraceTurn",
  "agentTraceDetailGroup",
  "agentTraceDetailSummary",
  "agentTraceDetailList",
  "agentTraceDetailItem",
  "sessionRow",
  "evidenceCard",
  "evidencePanel",
  "evidenceRequestPanel",
  "outputPanel",
  "cardPreviewIntro",
  "themeCard",
  "themeCard_selected",
  "themeCompareRow",
  "themeCompareRow_selected",
] as const;

const narrowOverflowGuardKeys = [
  "route",
  "workspace",
  "summaryGrid",
  "sessionRail",
  "sideColumn",
  "pipelinePanel",
  "processPanel",
  "stageRail",
  "agentTracePanel",
  "agentTraceTimeline",
  "themeGrid",
  "themeCompareMetrics",
] as const;

const contentSizedButtonKeys = [
  "primaryButton",
  "secondaryButton",
  "sessionButton",
  "sessionDeleteButton",
  "sourceToggleButton",
  "stageSelectButton",
  "traceBackToBottomButton",
  "traceGhostButton",
  "workflowModeButton",
] as const;

const denseResearchCardKeys = [
  "intakePanel",
  "historyPanel",
  "pipelinePanel",
  "processPanel",
  "stageCard",
  "stageCard_active",
  "stageCard_compact",
  "stageResultItem",
  "agentTracePanel",
  "agentTraceTurn",
  "agentTraceDetailGroup",
  "agentTraceDetailItem",
  "sessionRow",
  "evidenceCard",
  "evidenceRequestPanel",
  "themeCompareRow",
  "themeCompareRow_selected",
] as const;

function expectClassToken(className: string, token: string, message?: string) {
  expect(className.split(/\s+/), message).toContain(token);
}

function expectNoClassToken(className: string, token: string, message?: string) {
  expect(className.split(/\s+/), message).not.toContain(token);
}

describe("ResearchRoute layout contract", () => {
  it("routes Research controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VNativeTextarea");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
  });

  it("renders the API-backed theme discovery MVP", () => {
    expect(routeSource).toContain("ResearchRoute");
    expect(routeSource).toContain("/api/research/theme-discovery/sessions");
    expect(routeSource).toContain("/api/research/flow-canvas");
    expect(routeSource).toContain("/api/research/flow-canvas/execute");
    expect(routeSource).toContain("ResearchFlowCanvas");
    expect(routeSource).toContain("ResearchFlowExecutionResponse");
    expect(routeSource).toContain("AUTO_DRAFT_STEPS");
    expect(routeSource).toContain("runWorkflow");
    expect(routeSource).toContain("pauseAutoDraft");
    expect(routeSource).toContain("autoDraftPauseRequested");
    expect(routeSource).toContain("workflowMode");
    expect(routeSource).toContain('workflowMode === "auto"');
    expect(routeSource).toContain("autoDraftMutation.mutate");
    expect(routeSource).toContain("startIndex: autoDraftStartIndex(active)");
    expect(routeSource).toContain("manualWorkflowStep");
    expect(routeSource).toContain("showFallbackWorkflowModeControl");
    expect(routeSource).toContain("workflowControlsDisabled");
    expect(routeSource).not.toContain("enabled: activeView === \"discovery\"");
    expect(routeSource).not.toContain("activeView === \"discovery\"");
    expect(routeSource).toContain("initialPayload");
    expect(routeSource).toContain("autoDraftStepIndex");
    expect(routeSource).toContain("PREVIOUS_DEFAULT_INPUT");
    expect(routeSource).toContain("Qwen/千问");
    expect(routeSource).toContain("阿里云百炼平台");
    expect(routeSource).toContain("Problem Statement");
    expect(routeSource).toContain("科学价值 40 分、技术深度 30 分、应用潜力 30 分");
    expect(routeSource).toContain("nextManualWorkflowStep");
    expect(routeSource).toContain("flowStageItems");
    expect(routeSource).toContain("flowNodeStage");
    expect(routeSource).toContain("nextRunnableFlowNode");
    expect(routeSource).toContain("flowNodeCanExecute");
    expect(routeSource).toContain("runFlowNode");
    expect(routeSource).toContain("missingEvidenceRequests");
    expect(routeSource).toContain("confirmEvidenceSearch");
    expect(routeSource).toContain("candidateCardPreview");
    expect(routeSource).toContain("defaultCollapsed");
    expect(routeSource).not.toContain("CodeMirror");
    expect(routeSource).toContain("/agents/prompts?category=research");
    expect(routeSource).toContain("/research/flow-canvas");
    expect(routeSource).not.toContain("promptAgentRail");
    expect(routeSource).not.toContain("promptEditorPanel");
    expect(routeSource).not.toContain("promptInspectorPanel");
    expect(routeSource).toContain("run-broad-search");
    expect(routeSource).toContain("run-deep-search");
    expect(routeSource).toContain("extract-evidence");
    expect(routeSource).toContain("generate-themes");
    expect(routeSource).toContain("theme-card");
    expect(routeSource).toContain("method: \"DELETE\"");
    expect(routeSource).toContain("deleteSession");
    expect(routeSource).toContain("Candidate themes");
    expect(routeSource).not.toContain("Frontend preview");
  });

  it("keeps the page in the existing dense workbench layout family", () => {
    expect(styles.route).toBeTypeOf("string");
    expect(styles.summaryGrid).toBeTypeOf("string");
    expect(styles.workspace).toBeTypeOf("string");
    expect(styles.sessionRail).toBeTypeOf("string");
    expect(styles.intakeFields).toBeTypeOf("string");
    expect(styles.intakeField).toBeTypeOf("string");
    expect(styles.intakeField_primary).toBeTypeOf("string");
    expect(styles.intakeField_tall).toBeTypeOf("string");
    expect(styles.intakeField_medium).toBeTypeOf("string");
    expect(styles.sessionDeleteButton).toBeTypeOf("string");
    expect(styles.pipelinePanel).toBeTypeOf("string");
    expect(styles.evidencePanel).toBeTypeOf("string");
    expect(styles.outputPanel).toBeTypeOf("string");
    expect(styles.themeGrid).toBeTypeOf("string");
    const exportedClassNames = Object.keys(styles).join("\n");
    expect(exportedClassNames).not.toContain("promptWorkbench");
    expect(exportedClassNames).not.toContain("promptAgentRail");
    expect(exportedClassNames).not.toContain("promptEditorPanel");
    expect(exportedClassNames).not.toContain("promptInspectorPanel");
    expect(exportedClassNames).not.toContain("promptCodeEditor");
  });

  it("stacks workflow stages as full-width vertical rows", () => {
    expect(routeSource).toContain("styles.stageRail");
    expect(styles.stageRail).toBeTypeOf("string");
    expect(styles.stageCard).toBeTypeOf("string");
    expect(styles.stageCard_active).toBeTypeOf("string");
    expect(styles.stageCard_compact).toBeTypeOf("string");
    expect(styles.stageSelectButton).toBeTypeOf("string");
    expect(styles.stageBody).toBeTypeOf("string");
    expect(styles.workflowModeControl).toBeTypeOf("string");
    expect(styles.workflowModeButton_active).toBeTypeOf("string");
    expect(styles.evidenceRequestPanel).toBeTypeOf("string");
    expect(styles.agentTracePanel_collapsed).toBeTypeOf("string");
    expect(styles.cardPreviewIntro).toBeTypeOf("string");
    expect(styles.themeCard_selected).toBeTypeOf("string");
    expect(styles.themeCompareRow).toBeTypeOf("string");
    expect(styles.themeCompareMetrics).toBeTypeOf("string");
    expect(styles.themeCompareActions).toBeTypeOf("string");
    expect(routeSource).toContain("activeStage");
    expect(routeSource).toContain("ResearchStageOutput");
    expect(routeSource).toContain("AgentTracePanel");
    expect(routeSource).toContain("defaultCollapsed");
    expect(routeSource).toContain("stageDescription(stage, lang)");
    expect(routeSource).toContain("等待开始广撒网调研");
    expect(routeSource).toContain("等待抽取证据");
    expect(routeSource).toContain("等待生成候选主题");
    expect(routeSource).toContain("buildResearchTraceScrollSignal");
    expect(routeSource).toContain("ResearchTraceDetail");
    expect(routeSource).toContain("回到最新");
    expect(routeSource).toContain("工具调用与上下文过程");
    expect(routeSource).toContain("showAllSources");
    expect(routeSource).toContain("sourceToggleButton");
    expect(routeSource).toContain("formatTraceTimestamp");
    expect(routeSource).toContain("runFailure");
    expect(routeSource).toContain("failed");
    expect(styles.agentTracePanel).toBeTypeOf("string");
    expect(styles.agentTraceTimeline).toBeTypeOf("string");
    expect(styles.agentTraceTurn).toBeTypeOf("string");
    expect(styles.agentTraceDetailGroup).toBeTypeOf("string");
    expect(styles.traceBackToBottomButton).toBeTypeOf("string");
    expect(styles.agentTrace_error).toBeTypeOf("string");
  });

  it("moves research prompt editing to the Agent prompt center", () => {
    expect(routeSource).toContain("Agent 提示词中心");
    expect(routeSource).toContain("Agent prompt center");
    expect(routeSource).toContain("/agents/prompts?category=research");
    expect(routeSource).not.toContain("/api/research/theme-discovery/prompts");
    expect(routeSource).not.toContain("defaultContent");
    expect(routeSource).not.toContain("恢复默认提示词");
    expect(routeSource).not.toContain("Restore default prompt");
  });

  it("keeps restored research workbench grids from the CSS module migration", () => {
    expect(routeSource).toContain("styles.summaryCard");
    expect(styles.summaryCard).toContain("grid-cols-[auto_minmax(0,1fr)]");
    expect(styles.summaryCard).toContain("items-baseline");

    expect(routeSource).toContain("styles.sessionRow");
    expect(styles.sessionRow).toContain("grid-cols-[minmax(0,1fr)_34px]");

    expect(routeSource).toContain("styles.stageRail");
    expect(styles.stageRail).toContain("grid-cols-[1fr]");
    expect(styles.stageRail).toContain("overflow-y-auto");
    expect(styles.stageRail).toContain("overflow-x-hidden");
    expect(styles.stageRail).not.toContain("overflow-visible");

    expect(routeSource).toContain("styles.stageOutputHeader");
    expect(styles.stageOutputHeader).toContain("grid-cols-[22px_minmax(0,1fr)]");

    expect(routeSource).toContain("styles.agentTraceTurn");
    expect(styles.agentTraceTurn).toContain("grid-cols-[28px_minmax(0,1fr)]");

    expect(routeSource).toContain("styles.agentTraceDetailItem");
    expect(styles.agentTraceDetailItem).toContain("grid-cols-[24px_minmax(0,1fr)]");

    expect(routeSource).toContain("styles.themeCompareHeader");
    expect(styles.themeCompareHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");

    expect(routeSource).toContain("styles.themeHeader");
    expect(styles.themeHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(styles.themeHeader).toContain("gap-2.5");
  });

  it("keeps route and workspace chrome background-aware with mobile overflow guards", () => {
    expect(styles.route).toContain("max-w-full");
    expect(styles.route).toContain("overflow-x-hidden");
    expect(styles.route).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(styles.route).not.toContain("shadow-[var(--vui-shadow-hairline)]");

    expect(styles.workspace).toContain("max-w-full");
    expect(styles.workspace).toContain("overflow-x-hidden");
    expect(styles.workspace).toContain("grid-cols-[minmax(0,252px)_minmax(0,1fr)_minmax(0,252px)]");
    expect(styles.workspace).toContain("max-[1180px]:grid-cols-[minmax(0,220px)_minmax(0,1fr)_minmax(0,220px)]");
    expect(styles.workspace).toContain("gap-1.5");
    expect(styles.workspace).toContain("p-1.5");
    expect(styles.workspace).toContain("max-[980px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.workspace).toContain("max-[980px]:overflow-y-auto");
    expect(styles.workspace).toContain("max-[980px]:overflow-x-hidden");
    expect(styles.workspace).toContain("max-[980px]:p-1");
  });

  it("keeps dense research controls sized to their content", () => {
    for (const key of contentSizedButtonKeys) {
      const className = styles[key];

      expectClassToken(className, "w-fit", `${key} should not stretch across dense workbench rows`);
      expect(className, `${key} should still shrink inside narrow containers`).toContain("max-w-full");
      expectNoClassToken(className, "w-full", `${key} should avoid full-width button geometry`);
      expectNoClassToken(className, "flex-1", `${key} should avoid flex stretching`);
      expect(className, `${key} should keep a stable compact height`).toContain("min-h-[var(--vui-control-height-sm)]");
    }

    expect(styles.headerActions).toContain("flex-wrap");
    expect(styles.themeCompareActions).toContain("w-fit");
    expect(styles.themeCompareActions).toContain("flex-wrap");
    expect(styles.workflowModeControl).toContain("w-fit");
    expect(styles.agentTraceControls).toContain("justify-end");
  });

  it("tightens stage, session, theme, and trace cards for scan-first density", () => {
    for (const key of denseResearchCardKeys) {
      expect(styles[key], `${key} should use the compact Research padding`).toContain("p-1.5");
    }

    expect(styles.summaryGrid).toContain("gap-1.5");
    expect(styles.summaryGrid).toContain("grid-cols-[repeat(auto-fit,minmax(7.5rem,1fr))]");
    expect(styles.summaryCard).toContain("px-2");
    expect(styles.summaryCard).toContain("py-1.5");

    expect(styles.sessionRail).toContain("gap-1");
    expect(styles.sessionRow).toContain("grid-cols-[minmax(0,1fr)_34px]");
    expect(styles.stageRail).toContain("gap-1");
    expect(styles.stageOutputHeader).toContain("grid-cols-[22px_minmax(0,1fr)]");
    expect(styles.stageResultItems).toContain("gap-1");

    expect(styles.agentTraceAvatar).toContain("h-7");
    expect(styles.agentTraceAvatar).toContain("w-7");
    expect(styles.agentTraceTimeline).toContain("gap-1");
    expect(styles.agentTraceTurn).toContain("grid-cols-[28px_minmax(0,1fr)]");
    expect(styles.agentTraceDetailItem).toContain("grid-cols-[24px_minmax(0,1fr)]");

    expect(styles.themeGrid).toContain("grid-cols-[minmax(0,1fr)]");
    expect(styles.themeCompareMetrics).toContain("grid-cols-[repeat(auto-fit,minmax(7rem,1fr))]");
    expect(styles.themeCompareRow).toContain("p-1.5");
  });

  it("keeps the mobile research workbench single-column without horizontal spill", () => {
    expect(styles.workspace).toContain("max-[980px]:grid-rows-[auto_auto_auto]");
    expect(styles.workspace).toContain("max-[980px]:gap-1.5");
    expect(styles.sessionRail).toContain("max-[980px]:grid-cols-[repeat(2,minmax(0,1fr))]");
    expect(styles.sessionRail).toContain("max-[640px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.summaryGrid).toContain("max-[480px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.themeGrid).toContain("max-[640px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.themeCompareHeader).toContain("max-[640px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.themeHeader).toContain("max-[640px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.themeCompareActions).toContain("max-[640px]:justify-start");
    expect(styles.agentTraceDetailList).toContain("overflow-x-hidden");
  });

  it("keeps repeated research panels background-aware without strong glass or route shadows", () => {
    for (const key of majorResearchSurfaceKeys) {
      const className = styles[key];
      const backgroundToken = className.split(/\s+/).find(
        (token) =>
          token.startsWith("bg-[")
          || token.startsWith("!bg-[")
          || token.startsWith("bg-vui-surface-")
          || token.startsWith("!bg-vui-surface-"),
      );

      expect(backgroundToken, `${key} should declare an explicit background token`).toBeTruthy();
      expect(backgroundToken, `${key} background should use semantic VUI surface tokens`).toMatch(
        /vui-surface-|color-mix\(in_srgb/,
      );
      expect(backgroundToken, `${key} background should not restore an opaque VUI glass/card wall`).not.toContain(
        "var(--vui-surface-glass)",
      );
      expect(backgroundToken, `${key} background should not restore the raw surface-card token`).not.toContain(
        "var(--surface-card)",
      );
      expect(className).toMatch(/border-vui-border|border-\[(?:color:)?(?:color-mix|var\(--vui-border)/);
      expect(className).toMatch(/vui-surface-|color-mix\(in_srgb/);
      expect(className).not.toContain("bg-[var(--vui-surface-glass)]");
      expect(className).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    }
  });

  it("prevents narrow research surfaces from forcing horizontal overflow", () => {
    for (const key of narrowOverflowGuardKeys) {
      const className = styles[key];
      expect(className).toContain("min-w-0");
      expect(className).toContain("max-w-full");
    }

    expect(styles.route).toContain("overflow-x-hidden");
    expect(styles.workspace).toContain("overflow-x-hidden");
    expect(styles.headerActions).toContain("flex-wrap");
    expect(styles.panelHeader).toContain("flex-wrap");
    expect(styles.stageHeader).toContain("min-w-0");
    expect(styles.stageOutputHeader).toContain("min-w-0");
    expect(styles.agentTraceMeta).toContain("min-w-0");
    expect(styles.themeHeader).toContain("max-[640px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.themeCompareHeader).toContain("max-[640px]:grid-cols-[minmax(0,1fr)]");
  });

  it("keeps trace internals layout-only while the trace panel owns the surface", () => {
    for (const key of ["agentTraceHeader", "agentTraceControls", "agentTraceContent", "agentTraceMeta", "agentTraceTimeline"] as const) {
      expect(styles[key]).toContain("min-w-0");
      expect(styles[key]).not.toContain("bg-[color-mix");
      expect(styles[key]).not.toContain("border-[color-mix");
    }

    expect(styles.agentTracePanel).toMatch(
      /bg-\[(?:color:)?color-mix\(in_srgb,var\(--accent-cool\)_\d+%,transparent\)\]/,
    );
    expect(styles.agentTraceMeta).toContain("[&_strong]:text-[var(--fg-primary)]");
    expect(styles.primaryButton).toMatch(/bg-\[|!bg-\[|var\(--vui-surface/);
    expect(styles.primaryButton).not.toContain("var(--vui-surface-row)");
  });
});
