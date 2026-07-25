import "../design/route-css/workbench-secondary.tailwind.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckSquare, Clock3, FileText, GitBranch, GitCommitHorizontal, RefreshCw, Save, Square } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode, useEffect, useMemo, useState } from "react";

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
import { deriveQueryPresentation, type QueryPresentation } from "../app/queryPresentation";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import {
  VActionGroup,
  VButton,
  VIconButton,
  VLoadingValue,
  VMetricStrip,
  VNativeButton,
  VNativeSelect,
  VNativeTextarea,
  VDenseOpsPage,
  VStateSurface,
  VSurface,
} from "../components/vui";
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
import {
  migrateLegacyNumericPane,
  type PaneSpec,
} from "../components/layout/paneLayoutPersistence";
import { usePersistedPaneResize } from "../components/layout/usePersistedPaneResize";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { gitRouteStyles as styles } from "./GitRoute.styles";

const GIT_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.git;
const GIT_CHANGE_PANEL_WIDTH_KEY = "vibelution.git.change-panel-width";
const GIT_CHANGE_PANE: PaneSpec = {
  id: "change-panel",
  defaultWidth: 340,
  minWidth: 260,
  maxWidth: 520,
};
const GIT_CHANGE_PANES: PaneSpec[] = [GIT_CHANGE_PANE];

type GitWorktreeItem = GitStatusSummary["worktrees"]["items"][number];
type GitObjectSelection = {
  kind: "commit" | "branch" | "worktree";
  ref: string;
  path?: string;
  label: string;
  sourceLabel: string;
};

type GitRecentCommitsStateProps = {
  commitsContent: ReactNode;
  emptyMessage: ReactNode;
  errorLabel: ReactNode;
  loadingLabel: ReactNode;
  onRetry: () => void;
  presentation: QueryPresentation;
  retryLabel: ReactNode;
  syncingLabel?: ReactNode;
};

export function GitRecentCommitsState({
  commitsContent,
  emptyMessage,
  errorLabel,
  loadingLabel,
  onRetry,
  presentation,
  retryLabel,
  syncingLabel,
}: GitRecentCommitsStateProps) {
  if (presentation === "initial-loading") {
    return <VStateSurface tone="loading" title={loadingLabel} skeletonLines />;
  }
  if (presentation === "error-empty") {
    return (
      <VStateSurface
        tone="error"
        title={errorLabel}
        actions={(
          <VButton type="button" variant="secondary" onPress={onRetry}>{retryLabel}</VButton>
        )}
      />
    );
  }
  return (
    <>
      {presentation === "error-with-data" ? (
        <VStateSurface
          className={styles.notice}
          tone="error"
          title={errorLabel}
          actions={<VButton type="button" variant="secondary" onPress={onRetry}>{retryLabel}</VButton>}
        />
      ) : presentation === "refreshing" ? (
        <p className={styles.notice} role="status">{syncingLabel}</p>
      ) : null}
      <div className={styles.commitList}>
        {commitsContent || <p className={styles.emptyState}>{emptyMessage}</p>}
      </div>
    </>
  );
}

type GitStatusSummaryStateProps = {
  presentation: QueryPresentation;
  status?: GitStatusSummary;
  labels: {
    aria: string;
    branch: string;
    changed: string;
    upstream: string;
    aheadBehind: string;
    localCommits: string;
    worktrees: string;
  };
  loadingLabel: string;
  errorLabel: ReactNode;
  unavailableLabel: string;
  noUpstreamLabel: string;
  retryLabel: ReactNode;
  syncingLabel: ReactNode;
  onRetry: () => void;
};

export function GitStatusSummaryState({
  presentation,
  status,
  labels,
  loadingLabel,
  errorLabel,
  unavailableLabel,
  noUpstreamLabel,
  retryLabel,
  syncingLabel,
  onRetry,
}: GitStatusSummaryStateProps) {
  const loading = presentation === "initial-loading";
  const unavailable = presentation === "error-empty";
  const value = (resolved: ReactNode) => loading
    ? <VLoadingValue label={loadingLabel} />
    : unavailable
      ? unavailableLabel
      : resolved;
  const upstream = status?.upstream;
  const aheadBehind = upstream?.hasUpstream ? `${upstream.ahead} / ${upstream.behind}` : noUpstreamLabel;

  return (
    <>
      <VMetricStrip
        ariaLabel={labels.aria}
        className={styles.summaryGrid}
        metrics={[
          { id: "branch", label: labels.branch, value: value(status?.branch || status?.headRevShort || unavailableLabel) },
          { id: "changed", label: labels.changed, value: value(status?.counts.total ?? unavailableLabel) },
          { id: "upstream", label: labels.upstream, value: value(upstream?.name || upstream?.remote || noUpstreamLabel) },
          { id: "ahead-behind", label: labels.aheadBehind, value: value(aheadBehind) },
          { id: "local-commits", label: labels.localCommits, value: value(status?.localCommits?.total ?? upstream?.ahead ?? unavailableLabel) },
          { id: "worktrees", label: labels.worktrees, value: value(status?.worktrees ? `${status.worktrees.withCommits} / ${status.worktrees.total}` : unavailableLabel) },
        ]}
      />
      {presentation === "error-empty" || presentation === "error-with-data" ? (
        <VStateSurface
          className={styles.notice}
          title={errorLabel}
          tone="error"
          actions={<VButton type="button" variant="secondary" onPress={onRetry}>{retryLabel}</VButton>}
        />
      ) : presentation === "refreshing" ? (
        <p className={styles.notice} role="status">{syncingLabel}</p>
      ) : null}
    </>
  );
}

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
  const [changePanelCollapsed, setChangePanelCollapsed] = useState(false);
  useEffect(() => {
    migrateLegacyNumericPane(GIT_LAYOUT_ID, "change-panel", GIT_CHANGE_PANEL_WIDTH_KEY);
  }, []);
  const {
    layoutRef: gitLayoutRef,
    widths: gitPaneWidths,
    draggingPaneId: gitDraggingPaneId,
    startResize: startGitPaneResize,
    onResizeKeyDown: onGitPaneResizeKeyDown,
  } = usePersistedPaneResize({
    layoutId: GIT_LAYOUT_ID,
    panes: GIT_CHANGE_PANES,
    preserveMainMinWidth: 480,
  });
  const changePanelWidth = gitPaneWidths["change-panel"] ?? GIT_CHANGE_PANE.defaultWidth;
  const pageVisible = usePageVisibility();
  const locale = lang === "zh" ? "zh-CN" : "en-US";

  const statusQuery = useQuery({
    queryKey: queryKeys.gitStatus(),
    queryFn: ({ signal }) => fetchJson<GitStatusSummary>("/api/git/status?limit=500", { signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 6_000),
    refetchIntervalInBackground: false,
  });
  const commitsQuery = useQuery({
    queryKey: queryKeys.gitCommits(),
    queryFn: ({ signal }) => fetchJson<GitCommitsResponse>("/api/git/commits?limit=20", { signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
  });
  const configQuery = useQuery({
    queryKey: queryKeys.configWorkspace(),
    queryFn: ({ signal }) => fetchJson<ConfigWorkspace>("/api/config/workspace", { signal }),
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
    queryFn: ({ signal }) => fetchJson<GitFileDiff>(`/api/git/diff?path=${encodeURIComponent(activePath ?? "")}`, { signal }),
    enabled: Boolean(activePath && statusQuery.data?.available),
  });
  const objectDetailQuery = useQuery({
    queryKey: ["git", "object-detail", activeObject?.kind ?? "", activeObject?.ref ?? "", activeObject?.path ?? ""] as const,
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        kind: activeObject?.kind ?? "",
        ref: activeObject?.ref ?? "",
        path: activeObject?.path ?? "",
      });
      return fetchJson<GitObjectDetail>(`/api/git/object-detail?${params.toString()}`, { signal });
    },
    enabled: Boolean(activeObject && statusQuery.data?.available),
  });

  useEffect(() => {
    const availablePaths = new Set(files.map((file) => file.path));
    setSelectedPaths((current) => current.filter((path) => availablePaths.has(path)));
  }, [files]);

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
    void queryClient.invalidateQueries({ queryKey: queryKeys.gitStatusSummary() });
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
  const statusPresentation = deriveQueryPresentation({
    hasData: Boolean(statusQuery.data),
    isError: statusQuery.isError,
    isFetching: statusQuery.isFetching,
    isPending: statusQuery.isPending,
  });
  const commitsPresentation = deriveQueryPresentation({
    hasData: Boolean(commitsQuery.data),
    isError: commitsQuery.isError,
    isFetching: commitsQuery.isFetching,
    isPending: commitsQuery.isPending,
  });
  const statusInitialLoading = statusPresentation === "initial-loading";
  const statusEmptyError = statusPresentation === "error-empty";
  const gitStatusLoading = lang === "zh" ? "正在读取 Git 状态" : "Loading Git status";
  const gitStatusError = lang === "zh" ? "无法读取 Git 状态" : "Unable to load Git status";
  const gitCommitsLoading = lang === "zh" ? "正在读取最近提交" : "Loading recent commits";
  const gitCommitsError = lang === "zh" ? "无法读取最近提交" : "Unable to load recent commits";
  const retryLabel = lang === "zh" ? "重试" : "Retry";
  const unavailableLabel = lang === "zh" ? "不可用" : "Unavailable";
  const gitStatusSyncing = lang === "zh" ? "正在同步 Git 状态" : "Syncing Git status";
  const gitCommitsSyncing = lang === "zh" ? "正在同步最近提交" : "Syncing recent commits";
  const upstream = status?.upstream;
  const localCommitCount = status?.localCommits?.total ?? upstream?.ahead ?? 0;
  const worktreeBranchCount = status?.worktrees?.withCommits ?? 0;
  const worktreeTotalCount = status?.worktrees?.total ?? 0;
  const noChangedFiles = Boolean(
    status &&
      status.available &&
      (statusPresentation === "loaded" || statusPresentation === "refreshing") &&
      files.length === 0,
  );
  const localCommitPreview = (status?.localCommits?.commits ?? []).slice(0, 6);
  const pendingWorktrees = (status?.worktrees?.items ?? []).filter((item) => !item.isMain && item.hasCommits);
  const pendingWorktreePreview = pendingWorktrees.slice(0, 8);
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

  function handleChangePanelResizeStart(event: PointerEvent<any>) {
    if (changePanelCollapsed) {
      return;
    }
    startGitPaneResize("change-panel", event as PointerEvent<HTMLDivElement>, { direction: 1 });
  }

  function handleChangePanelResizeKeyDown(event: KeyboardEvent<any>) {
    if (changePanelCollapsed) {
      return;
    }
    onGitPaneResizeKeyDown("change-panel", event as KeyboardEvent<HTMLDivElement>, { direction: 1 });
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
      <VNativeButton
        key={commit.sha}
        type="button"
        className={active ? `${styles.commitItem} ${styles.objectItemActive}` : styles.commitItem}
        onClick={() =>
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
        <span className={styles.commitSubject}>{commit.subject}</span>
        <span className={styles.commitAuthor}>
          {t("gitCommitBy")}: {commit.author}
        </span>
      </VNativeButton>
    );
  }

  const recentCommitsContent = recentCommits.length
    ? recentCommits.map((commit) => renderCommitItem(commit, gitCommitSourceLabel))
    : null;
  const renderRecentCommitsContent = () => (
    <GitRecentCommitsState
      presentation={commitsPresentation}
      commitsContent={recentCommitsContent}
      emptyMessage={commitsQuery.data?.error || t("gitNoCommits")}
      errorLabel={gitCommitsError}
      loadingLabel={gitCommitsLoading}
      retryLabel={retryLabel}
      syncingLabel={gitCommitsSyncing}
      onRetry={() => void commitsQuery.refetch()}
    />
  );

  return (
    <VDenseOpsPage
      className={styles.route}
      headerClassName={styles.header}
      ariaLabel={t("gitPageTitle")}
      eyebrow={t("navGit")}
      title={t("gitPageTitle")}
      meta={t("gitPageSubtitle")}
      actions={(
        <VIconButton
          type="button"
          className={styles.refreshButton}
          label={t("gitRefresh")}
          icon={<RefreshCw size={16} />}
          onPress={refresh}
        />
      )}
    >
      <GitStatusSummaryState
        presentation={statusPresentation}
        status={status}
        labels={{
          aria: t("gitPageTitle"),
          branch: t("gitBranch"),
          changed: t("gitChangedFiles"),
          upstream: t("gitUpstream"),
          aheadBehind: t("gitAheadBehind"),
          localCommits: t("gitLocalCommits"),
          worktrees: t("gitWorktreeBranches"),
        }}
        loadingLabel={gitStatusLoading}
        errorLabel={statusQuery.error instanceof Error ? statusQuery.error.message : gitStatusError}
        unavailableLabel={unavailableLabel}
        noUpstreamLabel={t("gitNoUpstream")}
        retryLabel={retryLabel}
        syncingLabel={gitStatusSyncing}
        onRetry={() => void statusQuery.refetch()}
      />

      {status && !status.available && statusPresentation !== "error-empty" ? (
        <VStateSurface className={styles.notice} title={status.error || t("gitStatusUnavailable")} tone="unavailable" />
      ) : null}

      <div
        ref={gitLayoutRef}
        className={noChangedFiles ? `${styles.workspace} ${styles.workspaceOverview}` : styles.workspace}
        style={workspaceStyle}
        data-vui-layout-id={GIT_LAYOUT_ID}
      >
        {statusInitialLoading || statusEmptyError ? (
          <>
            {statusInitialLoading ? (
              <VStateSurface
                className={changePanelCollapsed ? `${styles.changePanel} ${styles.paneCollapsed}` : styles.changePanel}
                tone="loading"
                title={gitStatusLoading}
                skeletonLines
              />
            ) : (
              <VStateSurface
                className={changePanelCollapsed ? `${styles.changePanel} ${styles.paneCollapsed}` : styles.changePanel}
                tone="error"
                title={gitStatusError}
                actions={(
                <VButton type="button" variant="secondary" onPress={() => void statusQuery.refetch()}>{retryLabel}</VButton>
                )}
              />
            )}
            <PaneCollapseHandle
              side="left"
              collapsed={changePanelCollapsed}
              separatorLabel={resizeChangePanelLabel}
              collapseLabel={lang === "zh" ? "收起变更列表" : "Collapse changed files"}
              expandLabel={lang === "zh" ? "展开变更列表" : "Expand changed files"}
              className={styles.resizeHandle}
              active={gitDraggingPaneId === "change-panel"}
              valueNow={changePanelWidth}
              valueMin={GIT_CHANGE_PANE.minWidth}
              valueMax={GIT_CHANGE_PANE.maxWidth}
              onToggle={() => setChangePanelCollapsed((current) => !current)}
              onPointerDown={handleChangePanelResizeStart}
              onKeyDown={handleChangePanelResizeKeyDown}
            />
            {statusInitialLoading ? (
              <VStateSurface className={styles.diffPanel} tone="loading" title={gitStatusLoading} skeletonLines />
            ) : (
              <VStateSurface
                className={styles.diffPanel}
                tone="error"
                title={gitStatusError}
                actions={(
                  <VButton type="button" variant="secondary" onPress={() => void statusQuery.refetch()}>{retryLabel}</VButton>
                )}
              />
            )}
            <aside className={styles.commitPanel}>
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{t("gitHead")}</p>
                  <h2>{t("gitRecentCommits")}</h2>
                </div>
                <GitCommitHorizontal size={18} />
              </div>
              {renderRecentCommitsContent()}
            </aside>
          </>
        ) : noChangedFiles ? (
          <>
            <main className={styles.gitOverviewPanel}>
              <VNativeButton type="button" className={styles.cleanStateStrip} onClick={selectCurrentBranch}>
                <div>
                  <p className={styles.panelEyebrow}>{lang === "zh" ? "状态" : "Status"}</p>
                  <h2>{lang === "zh" ? "工作区干净" : "Clean worktree"}</h2>
                </div>
                <span>{status?.summary || (lang === "zh" ? "没有文件变更。" : "No changed files.")}</span>
              </VNativeButton>
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
                      <VNativeButton
                        key={`${item.path}-${item.branch}`}
                        type="button"
                        className={
                          activeObject?.kind === "worktree" && activeObject.path === item.path
                            ? `${styles.worktreeItem} ${styles.objectItemActive}`
                            : styles.worktreeItem
                        }
                        onClick={() => selectWorktree(item)}
                      >
                        <div>
                          <strong>{worktreeDisplayName(item)}</strong>
                          <span>{displayGitPath(item.path)}</span>
                        </div>
                        <code>+{item.aheadMain} / -{item.behindMain}</code>
                      </VNativeButton>
                    ))}
                    {!pendingWorktreePreview.length ? (
                      <p className={styles.emptyState}>{lang === "zh" ? "没有待合入 worktree 分支。" : "No worktree branches with pending commits."}</p>
                    ) : null}
                  </div>
                </section>
              </div>
            </main>
            <VSurface as="main" ariaLabel={t("gitFileDiff")} className={styles.objectDetailPanel} elevation="panel" padding="none" tone="rail">
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
                <VStateSurface className={styles.emptyPreview} icon={<GitBranch size={24} />} title={gitObjectDetailTitle} tone="empty">
                  {lang === "zh" ? "点击提交、分支或 worktree 查看内容。" : "Select a commit, branch, or worktree."}
                </VStateSurface>
              )}
            </VSurface>
            <VSurface as="aside" ariaLabel={t("gitRecentCommits")} className={`${styles.commitPanel} ${styles.historyPanel}`} elevation="panel" padding="none" tone="rail">
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{t("gitHead")}</p>
                  <h2>{t("gitRecentCommits")}</h2>
                </div>
                <GitCommitHorizontal size={18} />
              </div>
              {renderRecentCommitsContent()}
            </VSurface>
          </>
        ) : (
          <>
            <VSurface as="aside" ariaLabel={t("gitChangedScope")} className={changePanelCollapsed ? `${styles.changePanel} ${styles.paneCollapsed}` : styles.changePanel} elevation="panel" padding="none" tone="rail" aria-hidden={changePanelCollapsed}>
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
            </VSurface>

            <PaneCollapseHandle
              side="left"
              collapsed={changePanelCollapsed}
              separatorLabel={resizeChangePanelLabel}
              collapseLabel={lang === "zh" ? "收起变更列表" : "Collapse changed files"}
              expandLabel={lang === "zh" ? "展开变更列表" : "Expand changed files"}
              className={styles.resizeHandle}
              active={gitDraggingPaneId === "change-panel"}
              valueNow={changePanelWidth}
              valueMin={GIT_CHANGE_PANE.minWidth}
              valueMax={GIT_CHANGE_PANE.maxWidth}
              onToggle={() => setChangePanelCollapsed((current) => !current)}
              onPointerDown={handleChangePanelResizeStart}
              onKeyDown={handleChangePanelResizeKeyDown}
            />

            <VSurface as="main" ariaLabel={t("gitFileDiff")} className={styles.diffPanel} elevation="panel" padding="none" tone="rail">
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
                <VStateSurface className={styles.emptyPreview} icon={<GitBranch size={24} />} title={t("gitFileDiff")} tone="empty">
                  {statusQuery.isPending ? t("loading") : t("gitSelectFile")}
                </VStateSurface>
              )}
            </VSurface>

            <VSurface as="aside" ariaLabel={t("gitManualCommit")} className={styles.commitPanel} elevation="panel" padding="none" tone="rail">
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
              <VNativeSelect
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
              </VNativeSelect>
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
              <VNativeTextarea
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
              <VNativeTextarea
                rows={4}
                value={commitMessage}
                placeholder={t("gitCommitMessagePlaceholder")}
                onChange={(event) => setCommitMessage(event.target.value)}
              />
            </label>
            <VActionGroup ariaLabel={t("gitManualCommit")} className={styles.commitActions}>
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
            </VActionGroup>
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
          {renderRecentCommitsContent()}
        </VSurface>
          </>
        )}
      </div>
    </VDenseOpsPage>
  );
}
