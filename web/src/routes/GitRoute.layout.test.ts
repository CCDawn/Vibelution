import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { dictionary } from "../i18n/dictionary";
import routeSource from "./GitRoute.tsx?raw";
import { GitRecentCommitsState, GitStatusSummaryState } from "./GitRoute";
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

  it("uses VUI metrics, state, and action grouping without changing Git ownership", () => {
    expect(routeSource).toContain("VMetricStrip");
    expect(routeSource).toContain("VStateSurface");
    expect(routeSource).toContain("VActionGroup");
    expect(routeSource).toContain("commitSelected");
    expect(routeSource).toContain("generateMessage");
    expect(routeSource).toContain("stagedOutsideSelection");
    expect(routeSource).toContain("commitBlockReasonText");
    expect(routeSource).toContain("selectCurrentBranch");
    expect(routeSource).toContain("selectWorktree(item)");
    expect(gitRouteStyles.fileButton).toContain("grid-cols-[22px_34px_minmax(0,1fr)]");
    expect(gitRouteStyles.commitActions).toContain("flex");
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
    expect(gitRouteStyles.workspace).toContain("clamp(250px,22vw,360px)");
    expect(gitRouteStyles.workspace).not.toMatch(/minmax\((500|520)px/);
    expect(gitRouteStyles.workspace).not.toContain("minmax(250px,310px)");
    expect(gitRouteStyles.workspace).toContain("max-[860px]:grid-cols-[minmax(0,1fr)]");
    expect(gitRouteStyles.workspace).toContain("max-[860px]:content-start");
    expect(gitRouteStyles.workspaceOverview).toContain("minmax(0,1fr)");
    expect(gitRouteStyles.workspaceOverview).toContain("minmax(360px,1fr)");
    expect(gitRouteStyles.workspaceOverview).toContain("!grid-cols-");
    expect(gitRouteStyles.workspaceOverview).not.toMatch(/minmax\((500|520)px/);
    expect(gitRouteStyles.workspaceOverview).toContain("max-[860px]:!grid-cols-[minmax(0,1fr)]");
    expect(gitRouteStyles.diffPanel).toContain("min-w-0");
    expect(gitRouteStyles.objectDetailPanel).toContain("min-w-0");
  });

  it("keeps Git large surfaces translucent and action controls content-sized", () => {
    const largeSurfaceKeys = [
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
    expect(gitRouteStyles.commitActions).toContain("flex");
    expect(gitRouteStyles.commitActions).toContain("flex-wrap");
  });

  it("keeps Git summary and list rows dense without stretching controls", () => {
    expect(gitRouteStyles.summaryGrid).toContain("mx-2");
    expect(gitRouteStyles.summaryGrid).toContain("mt-1");
    expect(gitRouteStyles.summaryGrid).toContain("overflow-x-auto");
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
    expect(routeSource).toContain('queryFn: ({ signal }) => fetchJson<GitStatusSummary>("/api/git/status?limit=500", { signal })');
    expect(routeSource).toContain('queryFn: ({ signal }) => fetchJson<GitCommitsResponse>("/api/git/commits?limit=20", { signal })');
    expect(routeSource).toContain('queryFn: ({ signal }) => fetchJson<ConfigWorkspace>("/api/config/workspace", { signal })');
    expect(routeSource).toContain('fetchJson<GitFileDiff>(`/api/git/diff?path=${encodeURIComponent(activePath ?? "")}`, { signal })');
    expect(routeSource).toContain('fetchJson<GitObjectDetail>(`/api/git/object-detail?${params.toString()}`, { signal })');
    expect(routeSource).toContain("invalidateQueries({ queryKey: queryKeys.gitStatusSummary() })");
    expect(routeSource).toContain('tone="loading"');
    expect(routeSource).toContain("gitStatusLoading");
    expect(gitRouteStyles.summaryGrid).toContain("min-h-[48px]");
  });

  it("renders an aria-busy recent commits surface while commits load independently", () => {
    const markup = renderToStaticMarkup(createElement(GitRecentCommitsState, {
      presentation: "initial-loading",
      commitsContent: createElement("span", null, "old commit"),
      emptyMessage: "No commits",
      errorLabel: "Unable to load recent commits",
      loadingLabel: "Loading recent commits",
      retryLabel: "Retry",
      onRetry: vi.fn(),
    }));

    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("Loading recent commits");
    expect(markup).not.toContain("old commit");
  });

  it("wires empty commit errors to retry", () => {
    const onRetry = vi.fn();
    const state = GitRecentCommitsState({
      presentation: "error-empty",
      commitsContent: null,
      emptyMessage: "No commits",
      errorLabel: "Unable to load recent commits",
      loadingLabel: "Loading recent commits",
      retryLabel: "Retry",
      onRetry,
    }) as ReactElement<{ actions: ReactElement<{ onPress: () => void }> }>;

    state.props.actions.props.onPress();

    expect(onRetry).toHaveBeenCalledOnce();
    expect(renderToStaticMarkup(state)).toContain("Unable to load recent commits");
  });

  it.each(["error-with-data", "refreshing"] as const)("retains old commits for %s", (presentation) => {
    const markup = renderToStaticMarkup(createElement(GitRecentCommitsState, {
      presentation,
      commitsContent: createElement("span", null, "abc123 retained commit"),
      emptyMessage: "No commits",
      errorLabel: "Unable to load recent commits",
      loadingLabel: "Loading recent commits",
      retryLabel: "Retry",
      syncingLabel: "Syncing recent commits",
      onRetry: vi.fn(),
    }));

    expect(markup).toContain("abc123 retained commit");
    if (presentation === "error-with-data") {
      expect(markup).toContain("Unable to load recent commits");
      expect(markup).toContain("Retry");
    } else {
      expect(markup).not.toContain("Unable to load recent commits");
      expect(markup).toContain("Syncing recent commits");
    }
  });

  it("renders unavailable Git metrics for an empty status error and wires retry", () => {
    const onRetry = vi.fn();
    const state = GitStatusSummaryState({
      presentation: "error-empty",
      status: undefined,
      labels: {
        aria: "Git",
        branch: "Branch",
        changed: "Changed",
        upstream: "Upstream",
        aheadBehind: "Ahead / behind",
        localCommits: "Local commits",
        worktrees: "Worktrees",
      },
      loadingLabel: "Loading Git status",
      errorLabel: "Unable to load Git status",
      unavailableLabel: "Unavailable",
      noUpstreamLabel: "No upstream",
      retryLabel: "Retry",
      syncingLabel: "Syncing Git status",
      onRetry,
    }) as ReactElement;
    const markup = renderToStaticMarkup(state);

    expect(markup).toContain("Unavailable");
    expect(markup).not.toContain(">-<");
    expect(markup).not.toContain(">0<");
    expect(markup).not.toContain("No upstream");
    expect(markup).not.toContain("0 / 0");
    const retry = (state.props.children as ReactElement[])[1] as ReactElement<{ actions: ReactElement<{ onPress: () => void }> }>;
    retry.props.actions.props.onPress();
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it.each(["error-with-data", "refreshing"] as const)("retains status metrics for %s with a local action", (presentation) => {
    const onRetry = vi.fn();
    const markup = renderToStaticMarkup(createElement(GitStatusSummaryState, {
      presentation,
      status: {
        branch: "codex/loading-fix-git",
        headRevShort: "abc123",
        available: true,
        counts: { total: 4 },
        upstream: { hasUpstream: true, name: "origin/main", remote: "origin", ahead: 2, behind: 1 },
        localCommits: { total: 2 },
        worktrees: { withCommits: 1, total: 3 },
      },
      labels: {
        aria: "Git",
        branch: "Branch",
        changed: "Changed",
        upstream: "Upstream",
        aheadBehind: "Ahead / behind",
        localCommits: "Local commits",
        worktrees: "Worktrees",
      },
      loadingLabel: "Loading Git status",
      errorLabel: "Unable to load Git status",
      unavailableLabel: "Unavailable",
      noUpstreamLabel: "No upstream",
      retryLabel: "Retry",
      syncingLabel: "Syncing Git status",
      onRetry,
    }));

    expect(markup).toContain("codex/loading-fix-git");
    expect(markup).toContain("origin/main");
    if (presentation === "error-with-data") {
      expect(markup).toContain("Unable to load Git status");
      expect(markup).toContain("Retry");
    } else {
      expect(markup).toContain("Syncing Git status");
    }
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

  it("keeps clean Git branch and worktree detail previews reachable from the overview", () => {
    expect(routeSource).toContain("type GitObjectSelection");
    expect(routeSource).toContain("setActiveObject(selection)");
    expect(routeSource).toContain("/api/git/object-detail?");
    expect(routeSource).toContain("selectCurrentBranch");
    expect(routeSource).toContain("selectWorktree");
    expect(routeSource).toContain("selectWorktree(item)");
    expect(routeSource).toContain('kind: "worktree"');
    expect(routeSource).toContain('kind: "commit"');
    expect(routeSource).toContain("objectDetailQuery");
    expect(stylesSource).toContain("!grid-cols-[minmax(360px,1fr)_minmax(0,1.2fr)_minmax(300px,0.85fr)]");
    expect(stylesSource).toContain("clamp(250px,22vw,360px)");
    expect(stylesSource).toContain("max-[1200px]:grid-cols-1");
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
    expect(actionStyles).toContain("flex");
    expect(actionStyles).toContain("flex-wrap");
    expect(actionStyles).toContain("justify-end");
    expect(routeSource).toContain('title={t("gitAiPromptHint")}');
    expect(routeSource).toContain("title={aiDraftBlockReasonText || undefined}");
    expect(routeSource).toContain("title={commitBlockReasonText || undefined}");
    expect(routeSource).not.toContain('<span>{t("gitAiPromptHint")}</span>');
    expect(routeSource).not.toContain('<p className={styles.commitHint}>{t("gitCommitHint")}</p>');
  });

  it("keeps Git workspaces from forcing tall empty mobile stacks", () => {
    expect(stylesSource).toContain("max-[1200px]:grid-cols-1");
    expect(stylesSource).toContain("max-[860px]:!grid-cols-[minmax(0,1fr)]");
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
    expect(commitItemStyles).toContain("!grid");
    expect(commitItemStyles).toContain("grid-cols-1");
    expect(commitItemStyles).toContain("whitespace-normal");
    expect(commitItemStyles).not.toContain("data-slot=vui-button-content");
    expect(commitItemStyles).not.toContain("data-slot=vui-button-label");
    expect(gitRouteStyles.commitItem).toContain("bg-[color-mix(in_srgb,var(--vui-surface-row)");
    expect(stylesSource).toContain("commitSubject:");
    expect(stylesSource).toContain("commitAuthor:");
    expect(gitRouteStyles.commitSubject).toContain("text-ellipsis");
    expect(gitRouteStyles.commitAuthor).toContain("text-vui-fg-tertiary");
    expect(routeSource).toContain("styles.commitSubject");
    expect(routeSource).toContain("styles.commitAuthor");
  });
});
