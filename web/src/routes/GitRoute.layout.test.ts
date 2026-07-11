import { describe, expect, it } from "vitest";

import { dictionary } from "../i18n/dictionary";
import routeSource from "./GitRoute.tsx?raw";
import stylesSource from "./GitRoute.styles.ts?raw";
import { gitRouteStyles } from "./GitRoute.styles";
import diffStylesSource from "./GitDiffView.styles.ts?raw";
import diffStyles from "./GitDiffView.styles";
import diffViewSource from "./GitDiffView.tsx?raw";
import logicSource from "./gitRouteLogic.ts?raw";
import { gitRouteDictionary } from "./gitRouteI18n";
import gitRouteI18nSource from "./gitRouteI18n.ts?raw";
import shellDictionarySource from "../i18n/shellDictionary.ts?raw";

describe("GitRoute layout contract", () => {
  it("routes Git page controls through VUI primitives", () => {
    expect(routeSource).toContain("from \"../components/vui\"");
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VIconButton");
    expect(routeSource).toContain("<VNativeSelect");
    expect(routeSource).toContain("<VNativeTextarea");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
  });

  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useGitRouteI18n");
    expect(routeSource).toContain("const { lang, t } = useGitRouteI18n()");
    expect(routeSource).not.toContain("useAppI18n");
    expect(routeSource).not.toContain("useShellI18n");
    expect(diffViewSource).toContain("useGitRouteI18n");
    expect(diffViewSource).not.toContain("useAppI18n");
    expect(diffViewSource).not.toContain("useShellI18n");
    expect(logicSource).toContain("GitRouteTranslationKey");
    expect(logicSource).not.toContain("../i18n/dictionary");
    expect(logicSource).not.toContain("../i18n/shellDictionary");
  });

  it("keeps route-only Git copy out of the global shell dictionary", () => {
    expect(gitRouteI18nSource).toContain("gitCommitBlockedStagedOutsideSelection");
    expect(gitRouteI18nSource).toContain("gitAiPromptPlaceholder");
    expect(gitRouteI18nSource).toContain("readonlyPreview");
    expect(gitRouteI18nSource).toContain("previewTruncated");
    expect(shellDictionarySource).not.toContain("gitCommitBlockedStagedOutsideSelection");
    expect(shellDictionarySource).not.toContain("gitAiPromptPlaceholder");
    expect(shellDictionarySource).not.toContain("readonlyPreview");
    expect(shellDictionarySource).not.toContain("previewTruncated");
    expect(shellDictionarySource).toContain("gitStatusGuide");
  });

  it("keeps route-local Git copy aligned with the full app dictionary", () => {
    const keys = Object.keys(gitRouteDictionary.zh) as Array<keyof typeof gitRouteDictionary.zh>;

    for (const key of keys) {
      const routeKey = key as keyof typeof dictionary.zh;

      expect(gitRouteDictionary.zh[key]).toBe(dictionary.zh[routeKey]);
      expect(gitRouteDictionary.en[key]).toBe(dictionary.en[routeKey]);
    }
  });

  it("keeps the Git route shell background-aware and header chrome-light", () => {
    expect(gitRouteStyles.route).not.toContain("surface-page");
    expect(gitRouteStyles.route).not.toContain("bg-[var(--surface-page)]");
    expect(gitRouteStyles.route).not.toContain("bg-[color-mix(in_srgb,var(--surface-page)");
    expect(gitRouteStyles.header).not.toContain("surface-panel");
    expect(gitRouteStyles.header).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(gitRouteStyles.header).toContain("!bg-transparent");
    expect(gitRouteStyles.header).toContain("!shadow-none");
    expect(gitRouteStyles.header).toContain("!backdrop-blur-none");
  });

  it("keeps Git workspaces fluid on mobile and avoids hard desktop column floors", () => {
    expect(gitRouteStyles.route).toContain("overflow-hidden");
    expect(gitRouteStyles.route).toContain("overflow-x-hidden");
    expect(gitRouteStyles.workspace).toContain("min-w-0");
    expect(gitRouteStyles.workspace).toContain("minmax(0,1fr)");
    expect(gitRouteStyles.workspace).not.toMatch(/minmax\((500|520)px/);
    expect(gitRouteStyles.workspace).toContain("max-[860px]:grid-cols-[minmax(0,1fr)]");
    expect(gitRouteStyles.workspace).toContain("max-[860px]:content-start");
    expect(gitRouteStyles.workspaceOverview).toContain("minmax(0,1fr)");
    expect(gitRouteStyles.workspaceOverview).not.toMatch(/minmax\((500|520)px/);
    expect(gitRouteStyles.workspaceOverview).toContain("max-[860px]:grid-cols-[minmax(0,1fr)]");
    expect(gitRouteStyles.diffPanel).toContain("min-w-0");
    expect(gitRouteStyles.objectDetailPanel).toContain("min-w-0");
  });

  it("keeps Git large surfaces translucent and action controls content-sized", () => {
    const largeSurfaceKeys = [
      "summaryCard",
      "changePanel",
      "commitPanel",
      "gitSituationCard",
      "cleanStateStrip",
      "emptyPreview",
      "commitScopeBox",
    ] as const;
    const actionControlKeys = [
      "filterButton",
      "filterButtonActive",
      "selectionButton",
      "secondaryButton",
      "primaryButton",
    ] as const;

    for (const key of largeSurfaceKeys) {
      expect(gitRouteStyles[key]).not.toContain("bg-[var(--surface-panel)]");
      expect(gitRouteStyles[key]).toMatch(/bg-\[color-mix\(in_srgb,var\(--vui-surface-(panel|row)/);
    }
    for (const key of actionControlKeys) {
      expect(gitRouteStyles[key]).toContain("h-[var(--vui-control-height-sm)]");
      expect(gitRouteStyles[key]).not.toContain("bg-[var(--surface-card)]");
    }
    expect(gitRouteStyles.commitActions).toContain("grid-cols-[repeat(2,max-content)]");
    expect(gitRouteStyles.commitActions).toContain("max-[520px]:grid-cols-[1fr]");
  });

  it("keeps Git summary and list rows dense without stretching controls", () => {
    expect(gitRouteStyles.summaryGrid).toContain("grid-cols-[repeat(6,minmax(0,1fr))]");
    expect(gitRouteStyles.summaryGrid).toContain("max-[1180px]:grid-cols-[repeat(3,minmax(0,1fr))]");
    expect(gitRouteStyles.summaryGrid).toContain("max-[640px]:grid-cols-1");
    expect(gitRouteStyles.summaryCard).toContain("px-2");
    expect(gitRouteStyles.summaryCard).toContain("py-[5px]");
    expect(gitRouteStyles.changePanel).toContain("gap-1.5");
    expect(gitRouteStyles.changePanel).toContain("p-2");
    expect(gitRouteStyles.commitPanel).toContain("gap-1.5");
    expect(gitRouteStyles.fileButton).toContain("grid-cols-[22px_34px_minmax(0,1fr)]");
    expect(gitRouteStyles.fileButton).toContain("p-[6px]");
    expect(gitRouteStyles.fileButtonActive).toContain("grid-cols-[22px_34px_minmax(0,1fr)]");
  });

  it("keeps Git diff surfaces on lightweight VUI panels without losing code scroll semantics", () => {
    expect(diffStyles.surfaceClass).toContain("bg-vui-surface-panel");
    expect(diffStyles.surfaceClass).not.toContain("bg-[var(--surface-panel)]");
    expect(diffStyles.headerClass).toContain("border-vui-border-hairline");
    expect(diffStyles.headerClass).toContain("max-[640px]:flex-wrap");
    expect(diffStyles.fileNameClass).toContain("truncate");
    expect(diffStyles.diffWrapClass).toContain("overflow-auto");
    expect(diffStyles.diffWrapClass).toContain("bg-[var(--surface-code)]");
    expect(diffStyles.diffTableClass).toContain("w-max");
    expect(diffStyles.diffTableClass).toContain("leading-[1.42]");
    expect(diffStyles.lineContentClass).toContain("whitespace-pre");
    expect(diffStyles.columnHeaderClass).toContain("sticky");
    expect(diffStylesSource).toContain("grid-cols-[46px_46px_20px_minmax(0,1fr)]");
  });

  it("keeps commit actions scoped to selected files", () => {
    expect(routeSource).toContain("selectedPaths");
    expect(routeSource).toContain("stagedOutsideSelection");
    expect(routeSource).toContain("gitCommitSelected");
  });

  it("surfaces local commits and worktree branch pressure in the summary cards", () => {
    expect(routeSource).toContain("localCommitCount");
    expect(routeSource).toContain("worktreeBranchCount");
    expect(routeSource).toContain('t("gitLocalCommits")');
    expect(routeSource).toContain('t("gitWorktreeBranches")');
  });

  it("keeps Git summary cards visible without projecting pending status as zero", () => {
    expect(routeSource).toContain("deriveQueryPresentation");
    expect(routeSource).toContain("statusInitialLoading");
    expect(routeSource).toContain("<VLoadingValue");
    expect(routeSource).toContain('statusPresentation === "refreshing"');
    expect(routeSource).not.toContain("<strong>{status?.counts.total ?? 0}</strong>");
    expect(routeSource).not.toContain("<strong>{status?.branch || status?.headRevShort || \"-\"}</strong>");
  });

  it("reserves loading surfaces for the Git workspace panes", () => {
    expect(routeSource).toContain('tone="loading"');
    expect(routeSource).toContain("gitStatusLoading");
    expect(gitRouteStyles.summaryCard).toContain("min-h-");
  });

  it("switches clean worktrees to a Git situation overview instead of an empty diff workspace", () => {
    expect(routeSource).toContain("noChangedFiles");
    expect(routeSource).toContain("styles.workspaceOverview");
    expect(routeSource).toContain("styles.gitOverviewPanel");
    expect(routeSource).toContain("styles.cleanStateStrip");
    expect(routeSource).toContain("styles.gitSituationGrid");
    expect(routeSource).toContain("styles.objectDetailPanel");
    expect(routeSource).toContain("pendingWorktreePreview");
    expect(routeSource).toContain("localCommitPreview.map((commit) => renderCommitItem(commit, gitCommitSourceLabel))");
  });

  it("lets clean Git summaries open commit branch and worktree detail previews", () => {
    expect(routeSource).toContain("type GitObjectSelection");
    expect(routeSource).toContain("setActiveObject(selection)");
    expect(routeSource).toContain("/api/git/object-detail?");
    expect(routeSource).toContain("selectCurrentBranch");
    expect(routeSource).toContain("selectWorktree");
    expect(routeSource).toContain("worktreeDetailTarget");
    expect(routeSource).toContain('kind: "worktree"');
    expect(routeSource).toContain('kind: "commit"');
    expect(routeSource).toContain("objectDetailQuery");
    expect(stylesSource).toContain("grid-cols-[minmax(260px,0.9fr)_minmax(0,1.18fr)_minmax(240px,0.62fr)]");
    expect(stylesSource).toContain("objectDetailPanel:");
    expect(stylesSource).toContain("objectItemActive:");
  });

  it("keeps the clean Git overview history panel single-column at narrow desktop widths", () => {
    expect(stylesSource).toContain("historyPanel:");
    expect(stylesSource).toContain("max-[1200px]:[.workspaceOverview_&]:grid-cols-1");
    expect(stylesSource).toContain("max-[1200px]:[.workspaceOverview_&]:grid-rows-[auto_minmax(0,1fr)]");
  });

  it("keeps manual commit controls compact and moves helper copy to hover", () => {
    const manualCommitStyles = stylesSource.slice(stylesSource.indexOf("manualCommitPanel:"));
    const actionStyles = stylesSource.slice(stylesSource.indexOf("commitActions:"));

    expect(manualCommitStyles).toContain("max-h-[min(100%,calc(100dvh-178px))]");
    expect(manualCommitStyles).toContain("overflow-auto");
    expect(actionStyles).toContain("grid-cols-[repeat(2,max-content)]");
    expect(actionStyles).toContain("justify-end");
    expect(actionStyles).toContain("[&_.secondaryButton]:w-fit");
    expect(routeSource).toContain('title={t("gitAiPromptHint")}');
    expect(routeSource).toContain('title={t("gitCommitHint")}');
    expect(routeSource).not.toContain('<span>{t("gitAiPromptHint")}</span>');
    expect(routeSource).not.toContain('<p className={styles.commitHint}>{t("gitCommitHint")}</p>');
  });

  it("keeps Git workspaces from forcing tall empty mobile stacks", () => {
    expect(stylesSource).toContain("max-[860px]:grid-cols-1");
    expect(stylesSource).toContain("min-h-0");
    expect(stylesSource).not.toContain("min-height: 720px");
  });

  it("keeps the changed-file selection controls out of the scrollable file-list row", () => {
    expect(stylesSource).toContain("changePanel:");
    expect(stylesSource).toContain("grid-rows-[auto_auto_auto_minmax(0,1fr)]");
  });

  it("clips long commit titles inside Git cards without local horizontal scrolling", () => {
    const commitItemStyles = stylesSource.slice(stylesSource.indexOf("commitItem:"));

    expect(commitItemStyles).toContain("min-w-0");
    expect(routeSource).toContain("<VNativeButton");
    expect(commitItemStyles).toContain("grid");
    expect(commitItemStyles).toContain("min-h-[62px]");
    expect(commitItemStyles).not.toContain("!grid");
    expect(commitItemStyles).not.toContain("data-slot=vui-button-content");
    expect(commitItemStyles).not.toContain("data-slot=vui-button-label");
    expect(gitRouteStyles.commitItem).toContain("bg-[color-mix(in_srgb,var(--vui-surface-row)");
    expect(commitItemStyles).toContain("[&_strong]:block");
    expect(commitItemStyles).toContain("[&_strong]:max-w-full");
    expect(commitItemStyles).toContain("[&_strong]:text-ellipsis");
    expect(commitItemStyles).toContain("[&_strong]:whitespace-nowrap");
    expect(commitItemStyles).toContain("[&_strong]:leading-snug");
  });
});
