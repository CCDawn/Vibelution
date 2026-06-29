import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckSquare, Clock3, FileText, GitBranch, GitCommitHorizontal, RefreshCw, Save, Square } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  ConfigWorkspace,
  GitCommitSummary,
  GitCommitMessageResponse,
  GitCommitResponse,
  GitCommitsResponse,
  GitFileDiff,
  GitObjectDetail,
  GitStatusSummary,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import { VButton, VIconButton } from "../components/vui";
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

type GitWorktreeItem = GitStatusSummary["worktrees"]["items"][number];
type GitObjectSelection = {
  kind: "commit" | "branch" | "worktree";
  ref: string;
  path?: string;
  label: string;
  sourceLabel: string;
};

export function GitRoute() {
  const { lang, t } = useGitRouteI18n();
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState<GitFilter>("all");
  const [activePath, setActivePath] = useState<string | null>(null);
  const [activeObject, setActiveObject] = useState<GitObjectSelection | null>(null);
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
  const objectDetailQuery = useQuery({
    queryKey: ["git", "object-detail", activeObject?.kind ?? "", activeObject?.ref ?? "", activeObject?.path ?? ""] as const,
    queryFn: () => {
      const params = new URLSearchParams({
        kind: activeObject?.kind ?? "",
        ref: activeObject?.ref ?? "",
        path: activeObject?.path ?? "",
      });
      return fetchJson<GitObjectDetail>(`/api/git/object-detail?${params.toString()}`);
    },
    enabled: Boolean(activeObject && statusQuery.data?.available),
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
    if (activeObject) {
      void queryClient.invalidateQueries({ queryKey: ["git", "object-detail"] });
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
  const localCommitCount = status?.localCommits?.total ?? upstream?.ahead ?? 0;
  const worktreeBranchCount = status?.worktrees?.withCommits ?? 0;
  const worktreeTotalCount = status?.worktrees?.total ?? 0;
  const noChangedFiles = Boolean(status && status.available && !statusQuery.isPending && files.length === 0);
  const localCommitPreview = (status?.localCommits?.commits ?? []).slice(0, 6);
  const pendingWorktrees = (status?.worktrees?.items ?? []).filter((item) => !item.isMain && item.hasCommits);
  const pendingWorktreePreview = pendingWorktrees.slice(0, 8);
  const worktreeDetailTarget = pendingWorktrees[0] ?? (status?.worktrees?.items ?? []).find((item) => !item.isMain) ?? null;
  const recentCommits = commitsQuery.data?.commits ?? [];
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
  const gitObjectDetailTitle = lang === "zh" ? "对象详情" : "Object detail";
  const gitCommitSourceLabel = lang === "zh" ? "提交内容" : "Commit content";
  const gitBranchSourceLabel = lang === "zh" ? "分支内容" : "Branch content";
  const gitWorktreeSourceLabel = lang === "zh" ? "Worktree 内容" : "Worktree content";
  const activeObjectSourceLabel = activeObject?.sourceLabel ?? gitObjectDetailTitle;
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

  function worktreeDisplayName(item: GitWorktreeItem) {
    const normalizedPath = displayGitPath(item.path);
    return item.branch || normalizedPath.split("/").filter(Boolean).pop() || item.headRevShort || "-";
  }

  function selectGitObject(selection: GitObjectSelection) {
    setActiveObject(selection);
    setActivePath(null);
  }

  function selectCurrentBranch() {
    const branch = status?.branch || status?.headRevShort || "";
    if (!branch) {
      return;
    }
    selectGitObject({
      kind: "branch",
      ref: branch,
      label: branch,
      sourceLabel: gitBranchSourceLabel,
    });
  }

  function selectWorktree(item: GitWorktreeItem) {
    selectGitObject({
      kind: "worktree",
      ref: item.branch || item.headRev,
      path: item.path,
      label: worktreeDisplayName(item),
      sourceLabel: gitWorktreeSourceLabel,
    });
  }

  function selectFilePath(path: string) {
    setActiveObject(null);
    setActivePath(path);
  }

  function renderCommitItem(commit: GitCommitSummary, sourceLabel = gitCommitSourceLabel) {
    const active = activeObject?.kind === "commit" && activeObject.ref === commit.sha;
    return (
      <VButton
        key={commit.sha}
        type="button"
        variant="ghost"
        className={active ? `${styles.commitItem} ${styles.objectItemActive}` : styles.commitItem}
        onPress={() =>
          selectGitObject({
            kind: "commit",
            ref: commit.sha,
            label: `${commit.shortSha} ${commit.subject}`,
            sourceLabel,
          })
        }
      >
        <div className={styles.commitHeader}>
          <code>{commit.shortSha}</code>
          <span>
            <Clock3 size={13} />
            {formatGitDateTime(commit.authoredAt, locale)}
          </span>
        </div>
        <strong>{commit.subject}</strong>
        <p>{t("gitCommitBy")}: {commit.author}</p>
      </VButton>
    );
  }

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t("navGit")}</p>
          <h1 className={styles.title}>{t("gitPageTitle")}</h1>
          <p className={styles.subtitle}>{t("gitPageSubtitle")}</p>
        </div>
        <VButton type="button" variant="secondary" className={styles.refreshButton} icon={<RefreshCw size={16} />} onPress={refresh}>
          {t("gitRefresh")}
        </VButton>
      </header>

      <div className={styles.summaryGrid}>
        <VButton type="button" variant="ghost" className={styles.summaryCard} onPress={selectCurrentBranch} isDisabled={!status?.branch}>
          <span>{t("gitBranch")}</span>
          <strong>{status?.branch || status?.headRevShort || "-"}</strong>
        </VButton>
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
        <section className={styles.summaryCard}>
          <span>{t("gitLocalCommits")}</span>
          <strong>{localCommitCount}</strong>
        </section>
        <VButton
          type="button"
          variant="ghost"
          className={styles.summaryCard}
          onPress={() => {
            if (worktreeDetailTarget) {
              selectWorktree(worktreeDetailTarget);
            }
          }}
          isDisabled={!worktreeDetailTarget}
        >
          <span>{t("gitWorktreeBranches")}</span>
          <strong>{worktreeBranchCount} / {worktreeTotalCount}</strong>
        </VButton>
      </div>

      {!statusQuery.isPending && status && !status.available ? (
        <p className={styles.notice}>{status.error || t("gitStatusUnavailable")}</p>
      ) : null}

      <div className={noChangedFiles ? `${styles.workspace} ${styles.workspaceOverview}` : styles.workspace} style={workspaceStyle}>
        {noChangedFiles ? (
          <>
            <main className={styles.gitOverviewPanel}>
              <VButton type="button" variant="ghost" className={styles.cleanStateStrip} onPress={selectCurrentBranch}>
                <div>
                  <p className={styles.panelEyebrow}>{lang === "zh" ? "状态" : "Status"}</p>
                  <h2>{lang === "zh" ? "工作区干净" : "Clean worktree"}</h2>
                </div>
                <span>{status?.summary || (lang === "zh" ? "没有文件变更。" : "No changed files.")}</span>
              </VButton>
              <div className={styles.gitSituationGrid}>
                <section className={styles.gitSituationCard}>
                  <div className={styles.panelHeader}>
                    <div>
                      <p className={styles.panelEyebrow}>{t("gitUpstream")}</p>
                      <h2>{t("gitLocalCommits")}</h2>
                    </div>
                    <span className={styles.countPill}>{localCommitCount}</span>
                  </div>
                  <div className={styles.situationList}>
                    {localCommitPreview.map((commit) => renderCommitItem(commit, gitCommitSourceLabel))}
                    {!localCommitPreview.length ? (
                      <p className={styles.emptyState}>{lang === "zh" ? "没有本地提交待同步。" : "No local commits ahead of upstream."}</p>
                    ) : null}
                  </div>
                </section>
                <section className={styles.gitSituationCard}>
                  <div className={styles.panelHeader}>
                    <div>
                      <p className={styles.panelEyebrow}>WORKTREE</p>
                      <h2>{t("gitWorktreeBranches")}</h2>
                    </div>
                    <span className={styles.countPill}>{worktreeBranchCount} / {worktreeTotalCount}</span>
                  </div>
                  <div className={styles.worktreeList}>
                    {pendingWorktreePreview.map((item) => (
                      <VButton
                        key={`${item.path}-${item.branch}`}
                        type="button"
                        variant="ghost"
                        className={
                          activeObject?.kind === "worktree" && activeObject.path === item.path
                            ? `${styles.worktreeItem} ${styles.objectItemActive}`
                            : styles.worktreeItem
                        }
                        onPress={() => selectWorktree(item)}
                      >
                        <div>
                          <strong>{worktreeDisplayName(item)}</strong>
                          <span>{displayGitPath(item.path)}</span>
                        </div>
                        <code>+{item.aheadMain} / -{item.behindMain}</code>
                      </VButton>
                    ))}
                    {!pendingWorktreePreview.length ? (
                      <p className={styles.emptyState}>{lang === "zh" ? "没有待合入 worktree 分支。" : "No worktree branches with pending commits."}</p>
                    ) : null}
                  </div>
                </section>
              </div>
            </main>
            <main className={styles.objectDetailPanel}>
              {activeObject ? (
                <GitDiffView
                  path={activeObject.label}
                  diff={objectDetailQuery.data}
                  loading={objectDetailQuery.isPending}
                  changed
                  sourceLabel={objectDetailQuery.data?.statusLabel || activeObjectSourceLabel}
                  headerActions={
                    <span className={styles.inlineMeta}>
                      <GitBranch size={14} />
                      {activeObject.kind}
                    </span>
                  }
                />
              ) : (
                <div className={styles.emptyPreview}>
                  <GitBranch size={24} />
                  <strong>{gitObjectDetailTitle}</strong>
                  <p>{lang === "zh" ? "点击提交、分支或 worktree 查看内容。" : "Select a commit, branch, or worktree."}</p>
                </div>
              )}
            </main>
            <aside className={`${styles.commitPanel} ${styles.historyPanel}`}>
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{t("gitHead")}</p>
                  <h2>{t("gitRecentCommits")}</h2>
                </div>
                <GitCommitHorizontal size={18} />
              </div>
              <div className={styles.commitList}>
                {recentCommits.map((commit) => renderCommitItem(commit, gitCommitSourceLabel))}
                {!commitsQuery.isPending && !recentCommits.length ? (
                  <p className={styles.emptyState}>{commitsQuery.data?.error || t("gitNoCommits")}</p>
                ) : null}
              </div>
            </aside>
          </>
        ) : (
          <>
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
                  <VButton
                    key={filter}
                    type="button"
                    variant="secondary"
                    className={filter === activeFilter ? styles.filterButtonActive : styles.filterButton}
                    onPress={() => setActiveFilter(filter)}
                  >
                    {t(GIT_FILTER_LABEL_KEYS[filter])}
                  </VButton>
                ))}
              </div>
              <div className={styles.selectionRow}>
                <VButton type="button" variant="secondary" className={styles.selectionButton} onPress={selectVisible} isDisabled={!filteredFiles.length}>
                  {t("gitSelectVisible")}
                </VButton>
                <VButton type="button" variant="secondary" className={styles.selectionButton} onPress={clearSelection} isDisabled={!selectedCount}>
                  {t("gitClearSelection")}
                </VButton>
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
                      <VIconButton
                        type="button"
                        className={styles.fileCheckButton}
                        label={isSelected ? t("gitUnselectFile") : t("gitSelectFileForCommit")}
                        aria-pressed={isSelected}
                        icon={isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
                        onPress={() => toggleSelectedPath(file.path)}
                      />
                      <span className={styles.fileStatus}>{file.status}</span>
                      <VButton type="button" variant="ghost" className={styles.fileCopyButton} onPress={() => selectFilePath(file.path)}>
                        <strong>{gitFileName(file.path)}</strong>
                        <span className={styles.filePathText}>{displayGitPath(file.path)}</span>
                        <span className={styles.fileBadgeRow}>
                          {isActive ? <span className={styles.fileBadgeActive}>{t("gitPreviewing")}</span> : null}
                          {isSelected ? <span className={styles.fileBadgeSelected}>{t("gitSelectedForCommit")}</span> : null}
                        </span>
                      </VButton>
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
              {activeObject ? (
                <GitDiffView
                  path={activeObject.label}
                  diff={objectDetailQuery.data}
                  loading={objectDetailQuery.isPending}
                  changed
                  sourceLabel={objectDetailQuery.data?.statusLabel || activeObjectSourceLabel}
                  headerActions={
                    <span className={styles.inlineMeta}>
                      <GitBranch size={14} />
                      {activeObject.kind}
                    </span>
                  }
                />
              ) : activePath ? (
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
              <VButton
                type="button"
                variant="secondary"
                className={styles.secondaryButton}
                isDisabled={defaultModelSaveDisabled}
                onPress={saveDefaultAiModel}
                icon={<Save size={14} />}
              >
                {saveDefaultModelMutation.isPending ? t("gitAiSavingDefaultModel") : t("gitAiSaveDefaultModel")}
              </VButton>
            </div>
            <label className={`${styles.messageField} ${styles.promptTemplateField}`}>
              <span>{t("gitAiPromptTemplate")}</span>
              <textarea
                rows={4}
                value={aiPromptDraft}
                placeholder={t("gitAiPromptPlaceholder")}
                onChange={(event) => setAiPromptDraft(event.target.value)}
              />
            </label>
            <div className={`${styles.modelDefaultRow} ${styles.modelActionRow}`} title={t("gitAiPromptHint")}>
              <VButton
                type="button"
                variant="secondary"
                className={styles.secondaryButton}
                isDisabled={promptSaveDisabled}
                onPress={saveAiPrompt}
                title={t("gitAiPromptHint")}
                icon={<Save size={14} />}
              >
                {savePromptMutation.isPending ? t("gitAiPromptSaving") : t("gitAiPromptSave")}
              </VButton>
            </div>
            <label className={styles.messageField}>
              <span>{t("gitCommitMessage")}</span>
              <textarea
                rows={4}
                value={commitMessage}
                placeholder={t("gitCommitMessagePlaceholder")}
                onChange={(event) => setCommitMessage(event.target.value)}
              />
            </label>
            <div className={styles.commitActions} title={t("gitCommitHint")}>
              <VButton
                type="button"
                variant="secondary"
                className={styles.secondaryButton}
                onPress={generateMessage}
                isDisabled={aiDisabled}
                title={aiDraftBlockReasonText || undefined}
                icon={<Bot size={15} />}
              >
                {generateMessageMutation.isPending ? t("gitAiGenerating") : t("gitAiGenerateMessage")}
              </VButton>
              <VButton
                type="button"
                variant="primary"
                className={styles.primaryButton}
                onPress={commitSelected}
                isDisabled={commitDisabled}
                title={commitBlockReasonText || undefined}
                icon={<GitCommitHorizontal size={15} />}
              >
                {commitMutation.isPending ? t("gitCommitting") : t("gitCommitSelected")}
              </VButton>
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
          </section>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{t("gitHead")}</p>
              <h2>{t("gitRecentCommits")}</h2>
            </div>
            <GitCommitHorizontal size={18} />
          </div>
          <div className={styles.commitList}>
            {recentCommits.map((commit) => renderCommitItem(commit, gitCommitSourceLabel))}
            {!commitsQuery.isPending && !recentCommits.length ? (
              <p className={styles.emptyState}>{commitsQuery.data?.error || t("gitNoCommits")}</p>
            ) : null}
          </div>
            </aside>
          </>
        )}
      </div>
    </section>
  );
}
