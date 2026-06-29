import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { dictionary } from "../i18n/dictionary";
import routeSource from "./GitRoute.tsx?raw";
import diffViewSource from "./GitDiffView.tsx?raw";
import logicSource from "./gitRouteLogic.ts?raw";
import { gitRouteDictionary } from "./gitRouteI18n";
import gitRouteI18nSource from "./gitRouteI18n.ts?raw";
import shellDictionarySource from "../i18n/shellDictionary.ts?raw";

const stylesSource = readFileSync(new URL("./GitRoute.module.css", import.meta.url), "utf-8");

describe("GitRoute layout contract", () => {
  it("routes Git page controls through VUI primitives", () => {
    expect(routeSource).toContain("from \"../components/vui\"");
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VIconButton");
    expect(routeSource).not.toMatch(/<button\b/);
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
    expect(stylesSource).toContain("grid-template-columns: minmax(340px, 0.9fr) minmax(500px, 1.18fr) minmax(270px, 0.62fr)");
    expect(stylesSource).toContain(".objectDetailPanel");
    expect(stylesSource).toContain(".objectItemActive");
  });

  it("keeps the clean Git overview history panel single-column at narrow desktop widths", () => {
    expect(stylesSource).toContain(".workspace.workspaceOverview .historyPanel");
    expect(stylesSource).toContain("grid-template-columns: 1fr");
    expect(stylesSource).toContain("grid-template-rows: auto minmax(0, 1fr)");
  });

  it("keeps manual commit controls compact and moves helper copy to hover", () => {
    const manualCommitStyles = stylesSource.slice(stylesSource.indexOf(".manualCommitPanel"));
    const actionStyles = stylesSource.slice(stylesSource.indexOf(".commitActions"));

    expect(manualCommitStyles).toContain("max-height: min(100%, calc(100dvh - 190px))");
    expect(manualCommitStyles).toContain("overflow: auto");
    expect(actionStyles).toContain("grid-template-columns: repeat(2, max-content)");
    expect(actionStyles).toContain("justify-content: end");
    expect(actionStyles).toContain(".commitActions .secondaryButton");
    expect(actionStyles).toContain("width: fit-content");
    expect(routeSource).toContain('title={t("gitAiPromptHint")}');
    expect(routeSource).toContain('title={t("gitCommitHint")}');
    expect(routeSource).not.toContain('<span>{t("gitAiPromptHint")}</span>');
    expect(routeSource).not.toContain('<p className={styles.commitHint}>{t("gitCommitHint")}</p>');
  });

  it("keeps Git workspaces from forcing tall empty mobile stacks", () => {
    const mobileWorkspaceStyles = stylesSource.slice(stylesSource.indexOf("@media (max-width: 860px)"));

    expect(mobileWorkspaceStyles).toContain(".workspace {");
    expect(mobileWorkspaceStyles).toContain("min-height: 0");
    expect(mobileWorkspaceStyles).not.toContain("min-height: 720px");
  });

  it("clips long commit titles inside Git cards without local horizontal scrolling", () => {
    const commitItemStyles = stylesSource.slice(stylesSource.indexOf(".commitItem {"));
    const commitTitleStyles = stylesSource.slice(stylesSource.indexOf(".commitItem strong"));

    expect(commitItemStyles).toContain("min-width: 0");
    expect(commitTitleStyles).toContain("display: block");
    expect(commitTitleStyles).toContain("max-width: 100%");
    expect(commitTitleStyles).toContain("text-overflow: ellipsis");
    expect(commitTitleStyles).toContain("white-space: nowrap");
  });
});
