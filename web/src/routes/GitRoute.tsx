import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckSquare, Clock3, FileText, GitBranch, GitCommitHorizontal, RefreshCw, Save, Square } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ConfigWorkspace,
  GitCommitMessageResponse,
  GitCommitResponse,
  GitCommitsResponse,
  GitFileDiff,
  GitStatusSummary,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { GitDiffView } from "./GitDiffView";
import {
  getGitAiDraftBlockReason,
  getGitCommitBlockReason,
  getSelectedGitFiles,
  getStagedFilesOutsideSelection,
} from "./gitCommitUx";
import { useGitRouteI18n } from "./gitRouteI18n";
import {
  configuredGitModelId,
  configuredGitPrompt,
  displayGitPath,
  formatGitDateTime,
  gitFileName,
  gitFilterMatches,
  GIT_FILTER_LABEL_KEYS,
  GIT_FILTERS,
  type GitFilter,
} from "./gitRouteLogic";
import { clampPaneWidth, keyboardPaneWidth, storedPaneWidth } from "./resizablePane";
import styles from "./GitRoute.module.css";

const GIT_CHANGE_PANEL_WIDTH_KEY = "vibelution.git.change-panel-width";
const GIT_CHANGE_PANEL_BOUNDS = { min: 260, max: 520 };
const GIT_CHANGE_PANEL_DEFAULT_WIDTH = 340;

export function GitRoute() {
  const { lang, t } = useGitRouteI18n();
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState<GitFilter>("all");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [selectedAiModelId, setSelectedAiModelId] = useState("");
  const [aiPromptDraft, setAiPromptDraft] = useState("");
  const [commitMessage, setCommitMessage] = useState("");
  const [commitNotice, setCommitNotice] = useState<{ tone: "neutral" | "success" | "error"; text: string }>({
    tone: "neutral",
    text: "",
  });
  const [changePanelWidth, setChangePanelWidth] = useState(() =>
    storedPaneWidth(GIT_CHANGE_PANEL_WIDTH_KEY, GIT_CHANGE_PANEL_DEFAULT_WIDTH, GIT_CHANGE_PANEL_BOUNDS),
  );
  const [changePanelCollapsed, setChangePanelCollapsed] = useState(false);
  const pageVisible = usePageVisibility();
  const locale = lang === "zh" ? "zh-CN" : "en-US";

  const statusQuery = useQuery({
    queryKey: queryKeys.gitStatus(),
    queryFn: () => fetchJson<GitStatusSummary>("/api/git/status?limit=500"),
    refetchInterval: resolvePollingInterval(pageVisible, 6_000),
    refetchIntervalInBackground: false,
  });
  const commitsQuery = useQuery({
    queryKey: queryKeys.gitCommits(),
    queryFn: () => fetchJson<GitCommitsResponse>("/api/git/commits?limit=20"),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
  });
  const configQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: () => fetchJson<ConfigWorkspace>("/api/config/workspace"),
    staleTime: 30_000,
  });

  const files = statusQuery.data?.files ?? [];
  const filteredFiles = useMemo(
    () => files.filter((file) => gitFilterMatches(file, activeFilter)),
    [activeFilter, files],
  );
  const activeFile = files.find((file) => file.path === activePath) ?? null;
  const selectedSet = useMemo(() => new Set(selectedPaths), [selectedPaths]);
  const selectedCount = selectedPaths.length;
  const selectedFiles = useMemo(() => getSelectedGitFiles(files, selectedPaths), [files, selectedPaths]);
  const stagedOutsideSelection = useMemo(
    () => getStagedFilesOutsideSelection(files, selectedPaths),
    [files, selectedPaths],
  );
  const aiModelOptions = configQuery.data?.modelOptions ?? [];
  const configuredModelId = configuredGitModelId(configQuery.data);
  const configuredPrompt = configuredGitPrompt(configQuery.data);
  const activeAiModelId = selectedAiModelId || configuredModelId || aiModelOptions[0]?.model_id || "";
  const aiModelSelectOptions = useMemo(() => {
    if (!activeAiModelId || aiModelOptions.some((option) => option.model_id === activeAiModelId)) {
      return aiModelOptions;
    }
    return [
      {
        model_id: activeAiModelId,
        label: activeAiModelId,
        model: activeAiModelId,
      },
      ...aiModelOptions,
    ];
  }, [activeAiModelId, aiModelOptions]);

  useEffect(() => {
    if (!filteredFiles.length) {
      setActivePath(null);
      return;
    }
    if (!activePath || !filteredFiles.some((file) => file.path === activePath)) {
      setActivePath(filteredFiles[0].path);
    }
  }, [activePath, filteredFiles]);

  const diffQuery = useQuery({
    queryKey: queryKeys.gitDiff(activePath ?? ""),
    queryFn: () => fetchJson<GitFileDiff>(`/api/git/diff?path=${encodeURIComponent(activePath ?? "")}`),
    enabled: Boolean(activePath && statusQuery.data?.available),
  });

  useEffect(() => {
    const availablePaths = new Set(files.map((file) => file.path));
    setSelectedPaths((current) => current.filter((path) => availablePaths.has(path)));
  }, [files]);

  useEffect(() => {
    window.localStorage.setItem(GIT_CHANGE_PANEL_WIDTH_KEY, String(changePanelWidth));
  }, [changePanelWidth]);

  useEffect(() => {
    setAiPromptDraft(configuredPrompt);
  }, [configuredPrompt]);

  const generateMessageMutation = useMutation({
    mutationFn: (payload: { paths: string[]; modelId: string }) =>
      fetchJson<GitCommitMessageResponse>("/api/git/commit-message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: (payload) => {
      setCommitMessage(payload.message);
      setCommitNotice({ tone: "success", text: t("gitAiMessageReady") });
    },
    onError: (error) => {
      setCommitNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });
  const saveDefaultModelMutation = useMutation({
    mutationFn: (payload: { modelId: string }) =>
      fetchJson<{ modelId: string; previousModelId: string }>("/api/git/commit-message/default-model", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      setSelectedAiModelId("");
      setCommitNotice({ tone: "success", text: t("gitAiDefaultModelSaved") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() });
    },
    onError: (error) => {
      setCommitNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });
  const savePromptMutation = useMutation({
    mutationFn: (payload: { prompt: string }) =>
      fetchJson<{ prompt: string; previousPromptChars: number; promptChars: number }>("/api/git/commit-message/prompt", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      setCommitNotice({ tone: "success", text: t("gitAiPromptSaved") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() });
    },
    onError: (error) => {
      setCommitNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const commitMutation = useMutation({
    mutationFn: (payload: { paths: string[]; message: string }) =>
      fetchJson<GitCommitResponse>("/api/git/commit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    onSuccess: (payload) => {
      setCommitNotice({ tone: "success", text: `${t("gitCommitSuccess")} ${payload.shortSha}` });
      setSelectedPaths([]);
      setCommitMessage("");
      refresh();
    },
    onError: (error) => {
      setCommitNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.gitStatus() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.gitCommits() });
    if (activePath) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.gitDiff(activePath) });
    }
  };

  const toggleSelectedPath = (path: string) => {
    setSelectedPaths((current) => (current.includes(path) ? current.filter((item) => item !== path) : [...current, path]));
  };

  const selectVisible = () => {
    setSelectedPaths((current) => Array.from(new Set([...current, ...filteredFiles.map((file) => file.path)])));
  };

  const clearSelection = () => {
    setSelectedPaths([]);
  };

  const generateMessage = () => {
    setCommitNotice({ tone: "neutral", text: "" });
    generateMessageMutation.mutate({ paths: selectedPaths, modelId: activeAiModelId });
  };

  const saveDefaultAiModel = () => {
    setCommitNotice({ tone: "neutral", text: "" });
    saveDefaultModelMutation.mutate({ modelId: activeAiModelId });
  };

  const saveAiPrompt = () => {
    setCommitNotice({ tone: "neutral", text: "" });
    savePromptMutation.mutate({ prompt: aiPromptDraft });
  };

  const commitSelected = () => {
    setCommitNotice({ tone: "neutral", text: "" });
    commitMutation.mutate({ paths: selectedPaths, message: commitMessage });
  };

  const status = statusQuery.data;
  const upstream = status?.upstream;
  const aheadBehind = upstream?.hasUpstream ? `${upstream.ahead} / ${upstream.behind}` : t("gitNoUpstream");
  const commitBlockReason = getGitCommitBlockReason(
    selectedCount,
    commitMessage,
    commitMutation.isPending,
    stagedOutsideSelection.length,
  );
  const aiDraftBlockReason = getGitAiDraftBlockReason(selectedCount, generateMessageMutation.isPending);
  const commitDisabled = commitBlockReason !== null;
  const aiDisabled = aiDraftBlockReason !== null;
  const defaultModelSaveDisabled =
    saveDefaultModelMutation.isPending ||
    configQuery.isPending ||
    !activeAiModelId ||
    activeAiModelId === configuredModelId;
  const promptSaveDisabled = savePromptMutation.isPending || configQuery.isPending || !aiPromptDraft.trim() || aiPromptDraft === configuredPrompt;
  const commitBlockReasonText =
    commitBlockReason === "no_selection"
      ? t("gitCommitBlockedNoSelection")
      : commitBlockReason === "empty_message"
        ? t("gitCommitBlockedEmptyMessage")
        : commitBlockReason === "staged_outside_selection"
          ? t("gitCommitBlockedStagedOutsideSelection")
          : commitBlockReason === "committing"
            ? t("gitCommitBlockedCommitting")
            : "";
  const aiDraftBlockReasonText =
    aiDraftBlockReason === "no_selection"
      ? t("gitAiDraftBlockedNoSelection")
      : aiDraftBlockReason === "generating"
        ? t("gitAiDraftBlockedGenerating")
        : "";
  const selectedFilePreview = selectedFiles.slice(0, 5);
  const selectedOverflowCount = Math.max(0, selectedFiles.length - selectedFilePreview.length);
  const selectedCountText =
    lang === "zh" ? `已选 ${selectedCount} 个文件` : `${selectedCount} selected file${selectedCount === 1 ? "" : "s"}`;
  const selectedOverflowText =
    lang === "zh" ? `另有 ${selectedOverflowCount} 个文件` : `${selectedOverflowCount} more file${selectedOverflowCount === 1 ? "" : "s"}`;
  const workspaceStyle = useMemo(
    () =>
      ({
        "--git-change-panel-width": changePanelCollapsed ? "0px" : `${changePanelWidth}px`,
      }) as CSSProperties,
    [changePanelCollapsed, changePanelWidth],
  );
  const resizeChangePanelLabel = lang === "zh" ? "调整变更列表宽度" : "Resize changed files";

  function beginChangePanelResize(startX: number) {
    const startWidth = changePanelWidth;
    const handleMove = (moveEvent: globalThis.PointerEvent) => {
      setChangePanelWidth(clampPaneWidth(startWidth + moveEvent.clientX - startX, GIT_CHANGE_PANEL_BOUNDS));
    };
    const handleEnd = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleEnd);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleEnd);
  }

  function handleChangePanelResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    if (changePanelCollapsed) {
      return;
    }
    event.preventDefault();
    beginChangePanelResize(event.clientX);
  }

  function handleChangePanelResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (changePanelCollapsed) {
      return;
    }
    const nextWidth = keyboardPaneWidth(changePanelWidth, event.key, GIT_CHANGE_PANEL_BOUNDS);
    if (nextWidth === null) {
      return;
    }
    event.preventDefault();
    setChangePanelWidth(nextWidth);
  }

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t("navGit")}</p>
          <h1 className={styles.title}>{t("gitPageTitle")}</h1>
          <p className={styles.subtitle}>{t("gitPageSubtitle")}</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {t("gitRefresh")}
        </button>
      </header>

      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{t("gitBranch")}</span>
          <strong>{status?.branch || status?.headRevShort || "-"}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{t("gitChangedFiles")}</span>
          <strong>{status?.counts.total ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{t("gitUpstream")}</span>
          <strong>{upstream?.name || upstream?.remote || t("gitNoUpstream")}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{t("gitAheadBehind")}</span>
          <strong>{aheadBehind}</strong>
        </section>
      </div>

      {!statusQuery.isPending && status && !status.available ? (
        <p className={styles.notice}>{status.error || t("gitStatusUnavailable")}</p>
      ) : null}

      <div className={styles.workspace} style={workspaceStyle}>
        <aside className={changePanelCollapsed ? `${styles.changePanel} ${styles.paneCollapsed}` : styles.changePanel} aria-hidden={changePanelCollapsed}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{t("gitChangedScope")}</p>
              <h2>{t("gitAllChanges")}</h2>
            </div>
            <span className={styles.countPill}>{filteredFiles.length}</span>
          </div>
          <div className={styles.filterRow}>
            {GIT_FILTERS.map((filter) => (
              <button
                key={filter}
                type="button"
                className={filter === activeFilter ? styles.filterButtonActive : styles.filterButton}
                onClick={() => setActiveFilter(filter)}
              >
                {t(GIT_FILTER_LABEL_KEYS[filter])}
              </button>
            ))}
          </div>
          <div className={styles.selectionRow}>
            <button type="button" className={styles.selectionButton} onClick={selectVisible} disabled={!filteredFiles.length}>
              {t("gitSelectVisible")}
            </button>
            <button type="button" className={styles.selectionButton} onClick={clearSelection} disabled={!selectedCount}>
              {t("gitClearSelection")}
            </button>
          </div>
          <div className={styles.fileList}>
            {filteredFiles.map((file) => {
              const isActive = file.path === activePath;
              const isSelected = selectedSet.has(file.path);
              const fileCardClassName = [
                isActive ? styles.fileButtonActive : styles.fileButton,
                isSelected ? styles.fileButtonSelected : "",
              ]
                .filter(Boolean)
                .join(" ");
              return (
              <article
                key={`${file.status}-${file.path}`}
                className={fileCardClassName}
              >
                <button
                  type="button"
                  className={styles.fileCheckButton}
                  aria-label={isSelected ? t("gitUnselectFile") : t("gitSelectFileForCommit")}
                  aria-pressed={isSelected}
                  onClick={() => toggleSelectedPath(file.path)}
                >
                  {isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
                </button>
                <span className={styles.fileStatus}>{file.status}</span>
                <button type="button" className={styles.fileCopyButton} onClick={() => setActivePath(file.path)}>
                  <strong>{gitFileName(file.path)}</strong>
                  <span className={styles.filePathText}>{displayGitPath(file.path)}</span>
                  <span className={styles.fileBadgeRow}>
                    {isActive ? <span className={styles.fileBadgeActive}>{t("gitPreviewing")}</span> : null}
                    {isSelected ? <span className={styles.fileBadgeSelected}>{t("gitSelectedForCommit")}</span> : null}
                  </span>
                </button>
              </article>
              );
            })}
            {!filteredFiles.length ? <p className={styles.emptyState}>{t("gitNoMatchingChanges")}</p> : null}
          </div>
        </aside>

        <PaneCollapseHandle
          side="left"
          collapsed={changePanelCollapsed}
          separatorLabel={resizeChangePanelLabel}
          collapseLabel={lang === "zh" ? "收起变更列表" : "Collapse changed files"}
          expandLabel={lang === "zh" ? "展开变更列表" : "Expand changed files"}
          className={styles.resizeHandle}
          onToggle={() => setChangePanelCollapsed((current) => !current)}
          onPointerDown={handleChangePanelResizeStart}
          onKeyDown={handleChangePanelResizeKeyDown}
        />

        <main className={styles.diffPanel}>
          {activePath ? (
            <GitDiffView
              path={activePath}
              diff={diffQuery.data}
              loading={diffQuery.isPending}
              changed={Boolean(activeFile)}
              sourceLabel={activeFile?.statusLabel || t("gitFileDiff")}
              headerActions={
                <span className={styles.inlineMeta}>
                  <FileText size={14} />
                  {activeFile?.status || "-"}
                </span>
              }
            />
          ) : (
            <div className={styles.emptyPreview}>
              <GitBranch size={24} />
              <strong>{t("gitFileDiff")}</strong>
              <p>{statusQuery.isPending ? t("loading") : t("gitSelectFile")}</p>
            </div>
          )}
        </main>

        <aside className={styles.commitPanel}>
          <section className={styles.manualCommitPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{t("gitManualCommit")}</p>
                <h2>{t("gitCommitSelected")}</h2>
              </div>
              <span className={styles.countPill}>{selectedCount}</span>
            </div>
            <section className={styles.commitScopeBox} aria-label={t("gitCommitScopeTitle")}>
              <div className={styles.scopeHeader}>
                <div>
                  <span>{t("gitCommitScopeTitle")}</span>
                  <strong>{selectedCountText}</strong>
                </div>
                {selectedCount > 0 ? <span className={styles.scopeReady}>{t("gitSelectedForCommit")}</span> : null}
              </div>
              {selectedFilePreview.length ? (
                <div className={styles.scopeList}>
                  {selectedFilePreview.map((file) => (
                    <article key={file.path} className={styles.scopeItem}>
                      <span>{file.status}</span>
                      <strong>{displayGitPath(file.path)}</strong>
                    </article>
                  ))}
                  {selectedOverflowCount ? <p className={styles.scopeMore}>{selectedOverflowText}</p> : null}
                </div>
              ) : (
                <p className={styles.scopeEmpty}>{t("gitCommitScopeEmpty")}</p>
              )}
              {stagedOutsideSelection.length ? (
                <div className={styles.scopeWarning}>
                  <strong>{t("gitStagedOutsideSelectionTitle")}</strong>
                  <p>{t("gitStagedOutsideSelectionHint")}</p>
                  <span>{stagedOutsideSelection.slice(0, 3).map((file) => displayGitPath(file.path)).join(", ")}</span>
                </div>
              ) : null}
            </section>
            <label className={styles.messageField}>
              <span>{t("gitAiAgentLabel")}</span>
              <select
                value={activeAiModelId}
                disabled={!aiModelSelectOptions.length || configQuery.isPending}
                onChange={(event) => setSelectedAiModelId(event.target.value)}
              >
                {aiModelSelectOptions.length ? (
                  aiModelSelectOptions.map((option) => (
                    <option key={option.model_id} value={option.model_id}>
                      {option.label || option.model || option.model_id}
                    </option>
                  ))
                ) : (
                  <option value="">{t("gitAiAgentDefault")}</option>
                )}
              </select>
            </label>
            <div className={styles.modelDefaultRow}>
              <span>{configuredModelId ? `${t("gitAiCurrentDefault")} ${configuredModelId}` : t("gitAiNoDefaultModel")}</span>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={defaultModelSaveDisabled}
                onClick={saveDefaultAiModel}
              >
                <Save size={14} />
                {saveDefaultModelMutation.isPending ? t("gitAiSavingDefaultModel") : t("gitAiSaveDefaultModel")}
              </button>
            </div>
            <label className={`${styles.messageField} ${styles.promptTemplateField}`}>
              <span>{t("gitAiPromptTemplate")}</span>
              <textarea
                rows={5}
                value={aiPromptDraft}
                placeholder={t("gitAiPromptPlaceholder")}
                onChange={(event) => setAiPromptDraft(event.target.value)}
              />
            </label>
            <div className={styles.modelDefaultRow}>
              <span>{t("gitAiPromptHint")}</span>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={promptSaveDisabled}
                onClick={saveAiPrompt}
              >
                <Save size={14} />
                {savePromptMutation.isPending ? t("gitAiPromptSaving") : t("gitAiPromptSave")}
              </button>
            </div>
            <label className={styles.messageField}>
              <span>{t("gitCommitMessage")}</span>
              <textarea
                rows={6}
                value={commitMessage}
                placeholder={t("gitCommitMessagePlaceholder")}
                onChange={(event) => setCommitMessage(event.target.value)}
              />
            </label>
            <div className={styles.commitActions}>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={generateMessage}
                disabled={aiDisabled}
                title={aiDraftBlockReasonText || undefined}
              >
                <Bot size={15} />
                {generateMessageMutation.isPending ? t("gitAiGenerating") : t("gitAiGenerateMessage")}
              </button>
              <button
                type="button"
                className={styles.primaryButton}
                onClick={commitSelected}
                disabled={commitDisabled}
                title={commitBlockReasonText || undefined}
              >
                <GitCommitHorizontal size={15} />
                {commitMutation.isPending ? t("gitCommitting") : t("gitCommitSelected")}
              </button>
            </div>
            {commitNotice.text ? (
              <p className={commitNotice.tone === "error" ? styles.commitNoticeError : styles.commitNotice}>
                {commitNotice.text}
              </p>
            ) : commitBlockReasonText ? (
              <p className={styles.commitBlockReason}>{commitBlockReasonText}</p>
            ) : (
              <p className={styles.commitReady}>{t("gitCommitReady")}</p>
            )}
            {commitNotice.text ? null : (
              <p className={styles.commitHint}>{t("gitCommitHint")}</p>
            )}
          </section>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{t("gitHead")}</p>
              <h2>{t("gitRecentCommits")}</h2>
            </div>
            <GitCommitHorizontal size={18} />
          </div>
          <div className={styles.commitList}>
            {(commitsQuery.data?.commits ?? []).map((commit) => (
              <article key={commit.sha} className={styles.commitItem}>
                <div className={styles.commitHeader}>
                  <code>{commit.shortSha}</code>
                  <span>
                    <Clock3 size={13} />
                    {formatGitDateTime(commit.authoredAt, locale)}
                  </span>
                </div>
                <strong>{commit.subject}</strong>
                <p>{t("gitCommitBy")}: {commit.author}</p>
              </article>
            ))}
            {!commitsQuery.isPending && !(commitsQuery.data?.commits ?? []).length ? (
              <p className={styles.emptyState}>{commitsQuery.data?.error || t("gitNoCommits")}</p>
            ) : null}
          </div>
        </aside>
      </div>
    </section>
  );
}
