import { describe, expect, it } from "vitest";

import { dictionary } from "../i18n/dictionary";
import routeSource from "./GitRoute.tsx?raw";
import stylesSource from "./GitRoute.styles.ts?raw";
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
    expect(stylesSource).toContain("grid-cols-[minmax(340px,0.9fr)_minmax(500px,1.18fr)_minmax(270px,0.62fr)]");
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

    expect(manualCommitStyles).toContain("max-h-[min(100%,calc(100dvh-190px))]");
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
    expect(commitItemStyles).toContain("!grid");
    expect(commitItemStyles).toContain("!h-auto");
    expect(commitItemStyles).toContain("!min-h-[72px]");
    expect(commitItemStyles).toContain("[&_[data-slot=vui-button-content]]:!grid");
    expect(commitItemStyles).toContain("[&_[data-slot=vui-button-label]]:!grid");
    expect(commitItemStyles).toContain("[&_strong]:block");
    expect(commitItemStyles).toContain("[&_strong]:max-w-full");
    expect(commitItemStyles).toContain("[&_strong]:text-ellipsis");
    expect(commitItemStyles).toContain("[&_strong]:whitespace-nowrap");
    expect(commitItemStyles).toContain("[&_strong]:leading-snug");
  });
});
