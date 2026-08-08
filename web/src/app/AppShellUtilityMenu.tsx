import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Activity, ExternalLink, FolderTree, GitBranch, ScrollText, Search } from "lucide-react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { FileTreeNode, GitStatusSummary } from "../api/types";
import {
  VButton,
  VChip,
  VMetricStrip,
  VNativeInput,
  VPanelHeader,
  VRouteLinkButton,
  VSurface,
  VTooltip,
  type VuiTone,
} from "../components/vui";
import type { Language, ShellTranslationKey } from "../i18n/shellDictionary";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import { resolvePollingInterval } from "./pollingPolicy";
import type { SystemStatusTone } from "./systemStatus";
import styles from "./AppShellUtilityMenu.styles";

function gitToneToVui(tone: SystemStatusTone): VuiTone {
  if (tone === "running") return "success";
  if (tone === "caution") return "warning";
  if (tone === "failed") return "danger";
  return "neutral";
}

export type AppShellUtilityMenuProps = {
  lang: Language;
  t: (key: ShellTranslationKey) => string;
  frontendVisible: boolean;
  onClose: () => void;
};

function filterUtilityFileTree(nodes: FileTreeNode[], query: string): FileTreeNode[] {
  const term = query.trim().toLowerCase();
  if (!term) {
    return nodes;
  }
  return nodes.flatMap((node) => {
    const matches = node.name.toLowerCase().includes(term) || node.path.toLowerCase().includes(term);
    if (node.type === "directory") {
      const filteredChildren = filterUtilityFileTree(node.children ?? [], query);
      if (matches) {
        return [{ ...node, children: node.children ?? [] }];
      }
      if (filteredChildren.length > 0) {
        return [{ ...node, children: filteredChildren }];
      }
      return [];
    }
    return matches ? [node] : [];
  });
}

function renderUtilityFileTree(
  nodes: FileTreeNode[],
  onOpenFile: (path: string) => void,
  activeFilePath: string,
) {
  return nodes.map((node) => {
    if (node.type === "directory") {
      return (
        <details key={node.path} className={styles.utilityFileDir} open>
          <summary>{node.name}</summary>
          <div className={styles.utilityFileChildren}>
            {renderUtilityFileTree(node.children ?? [], onOpenFile, activeFilePath)}
          </div>
        </details>
      );
    }
    const active = activeFilePath === node.path;
    return (
      <VButton
        key={node.path}
        type="button"
                contentLayout="plain"
        className={active ? `${styles.utilityFileButton} ${styles.utilityFileButtonActive}` : styles.utilityFileButton}
        onPress={() => onOpenFile(node.path)}
        tooltip={node.path}
      >
        <span>{node.name}</span>
        <small>{node.path}</small>
      </VButton>
    );
  });
}

function compactWorktreePath(path: string) {
  return path.replaceAll("\\", "/").split("/").filter(Boolean).at(-1) || path;
}

function utilityNavClass(pathname: string, to: string) {
  const active = pathname === to || pathname.startsWith(`${to}/`);
  return active ? `${styles.utilityButton} ${styles.utilityButtonActive}` : styles.utilityButton;
}

export function AppShellUtilityMenu({ lang, t, frontendVisible, onClose }: AppShellUtilityMenuProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [utilityFileFilter, setUtilityFileFilter] = useState("");
  const [fileTreeRequested, setFileTreeRequested] = useState(false);
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const activeSessionWorkspace = useChatWorkbenchStore((state) =>
    state.activeSessionId ? state.sessionWorkspaces[state.activeSessionId] : undefined,
  );
  const openPreviewTab = useChatWorkbenchStore((state) => state.openPreviewTab);
  const gitRefetchInterval = resolvePollingInterval(frontendVisible, 6_000, { backgroundMs: 60_000 });
  const gitStatusQuery = useQuery({
    queryKey: queryKeys.gitStatusSummary(),
    queryFn: ({ signal }) => fetchJson<GitStatusSummary>("/api/git/status", { signal }),
    refetchInterval: gitRefetchInterval,
    refetchIntervalInBackground: false,
  });
  const fileTreeQuery = useQuery({
    queryKey: queryKeys.fileTree(),
    queryFn: ({ signal }) => fetchJson<FileTreeNode[]>("/api/files/tree", { signal }),
    enabled: fileTreeRequested,
    refetchOnWindowFocus: false,
    staleTime: 30_000,
    gcTime: 120_000,
  });

  const gitStatus = gitStatusQuery.data;
  const utilityFilteredFileTree = useMemo(
    () => filterUtilityFileTree(fileTreeQuery.data ?? [], utilityFileFilter),
    [fileTreeQuery.data, utilityFileFilter],
  );
  const utilityActiveFilePath = activeSessionWorkspace?.activeTab && activeSessionWorkspace.activeTab !== "agent"
    ? activeSessionWorkspace.activeTab
    : "";
  const gitAvailable = Boolean(gitStatus?.available);
  const gitDirty = Boolean(gitStatus?.dirty);
  const gitAttention = Boolean(gitStatus?.requiresAttention ?? gitDirty);
  const gitTone: SystemStatusTone = gitAvailable ? (gitAttention ? "caution" : "running") : "idle";
  const gitBranch = gitStatus?.branch || gitStatus?.headRevShort || "-";
  const gitAhead = gitStatus?.upstream?.ahead ?? 0;
  const gitBehind = gitStatus?.upstream?.behind ?? 0;
  const gitLocalCommits = gitStatus?.localCommits?.total ?? gitAhead;
  const gitWorktreeCommits = gitStatus?.worktrees?.withCommits ?? 0;
  const gitDirtyCount = gitStatus?.counts.total ?? 0;
  const gitPendingWorktrees = (gitStatus?.worktrees?.items ?? []).filter((item) => !item.isMain && item.hasCommits);
  const gitStatusLevel = gitStatus?.statusLevel ?? (gitDirty ? "dirty" : "clean");
  const gitHeroLabel = !gitAvailable
    ? gitStatusQuery.isPending
      ? t("gitChecking")
      : t("gitUnavailable")
    : gitStatusLevel === "diverged"
      ? t("gitStateDiverged")
      : gitStatusLevel === "behind"
        ? t("gitStateBehind")
        : gitLocalCommits > 0
          ? t("gitStateLocalCommits")
          : gitWorktreeCommits > 0
            ? t("gitStateWorktreeCommits")
            : gitDirtyCount > 0
              ? t("gitStateDirty")
              : t("gitStateClean");
  const gitValue = gitAvailable
    ? gitLocalCommits > 0
      ? `+${gitLocalCommits}`
      : gitBehind > 0
        ? `-${gitBehind}`
        : gitWorktreeCommits > 0
          ? `${gitWorktreeCommits} wt`
          : gitDirty
      ? `${gitDirtyCount}`
      : t("gitClean")
    : gitStatusQuery.isPending
      ? t("gitChecking")
      : t("gitUnavailable");
  const gitTitle = gitAvailable
    ? `${t("gitStatus")}: ${gitStatus?.summary ?? ""}`
    : gitStatus?.error || t("gitUnavailable");
  const utilityFileNavigatorHint = activeSessionId
    ? (lang === "zh" ? "点击文件会在当前会话工作区打开预览。" : "Click a file to open it in the current chat workspace.")
    : (lang === "zh" ? "先进入会话后可打开文件预览。" : "Open a chat first to preview files.");
  const requestUtilityFileTree = useCallback(() => {
    setFileTreeRequested(true);
  }, []);
  const handleUtilityOpenFile = useCallback((path: string) => {
    if (!activeSessionId) {
      navigate("/chat");
      onClose();
      return;
    }
    openPreviewTab(activeSessionId, path);
    navigate("/chat");
    onClose();
  }, [activeSessionId, navigate, onClose, openPreviewTab]);

  return (
    <div
      className={styles.utilityPanel}
      role="region"
      aria-label={t("topUtilityMenu")}
    >
      <VTooltip content={t("topUtilityMenuHint")} width="wide">
        <div
          className={styles.utilityPanelHeader}
          tabIndex={0}
          aria-label={`${t("topUtilityMenu")}: ${t("topUtilityMenuHint")}`}
        >
          <strong>{t("topUtilityMenu")}</strong>
        </div>
      </VTooltip>
      <div className={styles.utilityButtonGrid}>
        {/* External control surface: native anchor (not SPA Link) per VRouteLinkButton design boundary. */}
        <a href="/launcher" target="_blank" rel="noreferrer" className={styles.utilityButton} onClick={onClose}>
          <ExternalLink size={16} />
          <span>{lang === "zh" ? "启动器" : "Launcher"}</span>
        </a>
        <VTooltip content={t("usageUtilityTitle")}>
          <VRouteLinkButton
            to="/usage"
            className={utilityNavClass(location.pathname, "/usage")}
            onClick={onClose}
            icon={<Activity size={16} aria-hidden="true" />}
          >
            {t("navUsage")}
          </VRouteLinkButton>
        </VTooltip>
        <VRouteLinkButton
          to="/logs"
          className={utilityNavClass(location.pathname, "/logs")}
          onClick={onClose}
          icon={<ScrollText size={16} aria-hidden="true" />}
        >
          {t("navLogs")}
        </VRouteLinkButton>
        <VRouteLinkButton
          to="/git"
          className={utilityNavClass(location.pathname, "/git")}
          onClick={onClose}
          icon={<GitBranch size={16} aria-hidden="true" />}
        >
          {t("navGit")}
        </VRouteLinkButton>
        <VButton
          type="button"
          contentLayout="plain"
          className={styles.utilityButton}
          onPress={() => {
            requestUtilityFileTree();
            window.requestAnimationFrame(() => document.getElementById("utility-file-navigator")?.scrollIntoView({ block: "nearest" }));
          }}
        >
          <FolderTree size={16} aria-hidden />
          <span>{t("files")}</span>
        </VButton>
      </div>
      <VSurface
        tone="card"
        elevation="flat"
        padding="compact"
        className={styles.gitMiniPanel}
        ariaLabel={`${t("gitStatusGuide")}: ${gitTitle}`}
        tabIndex={0}
      >
        <VPanelHeader
          headingLevel={3}
          className={styles.gitPanelHeader}
          title={gitHeroLabel}
          eyebrow={t("gitStatus")}
          tooltip={gitTitle}
          tooltipLabel={t("gitStatusGuide")}
          actions={(
            <VRouteLinkButton to="/git" className={styles.gitOpenLink} onClick={onClose}>
              {t("navGit")}
            </VRouteLinkButton>
          )}
        />
        <div className={styles.gitChipRow}>
          <GitBranch size={12} aria-hidden="true" />
          <VChip tone={gitToneToVui(gitTone)} className={styles.gitBranchChip}>
            {gitBranch}
          </VChip>
          {gitValue ? (
            <VChip tone={gitToneToVui(gitTone)} className={styles.gitValueChip}>
              {gitValue}
            </VChip>
          ) : null}
        </div>
        <p className={styles.gitSummaryLine}>{gitStatus?.summary || t("gitStatusGuideHint")}</p>
        <div className={styles.gitMetricStack}>
          <VMetricStrip
            ariaLabel={t("gitStatusGuide")}
            className={styles.gitMetricStrip}
            status={{
              label: gitValue,
              title: gitTitle,
              tone: gitToneToVui(gitTone),
              ariaLabel: `${t("gitStatus")}: ${gitValue}`,
            }}
            metrics={[
              { id: "ahead", label: t("gitLocalAhead"), value: gitLocalCommits, tone: gitLocalCommits > 0 ? "info" : "neutral" },
              { id: "behind", label: t("gitRemoteBehind"), value: gitBehind, tone: gitBehind > 0 ? "warning" : "neutral" },
              { id: "wt-pending", label: t("gitWorktreesPending"), value: gitWorktreeCommits, tone: gitWorktreeCommits > 0 ? "warning" : "neutral" },
              { id: "dirty", label: t("gitWorkingTree"), value: gitDirtyCount, tone: gitDirtyCount > 0 ? "warning" : "success" },
            ]}
          />
          <details className={styles.gitDetails}>
            <summary className={styles.gitDetailsSummary}>
              {lang === "zh" ? "工作区明细" : "Working tree details"}
            </summary>
            <VMetricStrip
              ariaLabel={t("gitWorkingTree")}
              className={styles.gitMetricStrip}
              metrics={[
                { id: "branch", label: t("gitBranch"), value: gitBranch },
                {
                  id: "upstream",
                  label: t("gitUpstream"),
                  value: gitStatus?.upstream?.name || gitStatus?.upstream?.remote || t("gitNoUpstream"),
                },
                {
                  id: "worktrees",
                  label: t("gitWorktrees"),
                  value: `${gitWorktreeCommits} / ${gitStatus?.worktrees?.total ?? 0}`,
                },
                { id: "staged", label: t("gitStaged"), value: gitStatus?.counts.staged ?? 0 },
                { id: "unstaged", label: t("gitUnstaged"), value: gitStatus?.counts.unstaged ?? 0 },
                { id: "untracked", label: t("gitUntracked"), value: gitStatus?.counts.untracked ?? 0 },
                { id: "deleted", label: t("gitDeleted"), value: gitStatus?.counts.deleted ?? 0 },
              ]}
            />
          </details>
        </div>
        {gitStatus?.localCommits?.commits?.length ? (
          <section className={styles.gitSection} aria-label={t("gitLocalCommits")}>
            <div className={styles.gitSectionHeader}>
              <strong>{t("gitLocalCommits")}</strong>
              <VChip tone="neutral">
                {gitStatus.localCommits.truncated ? t("gitListTruncated") : `${gitStatus.localCommits.total}`}
              </VChip>
            </div>
            <div className={styles.gitCommitList}>
              {gitStatus.localCommits.commits.slice(0, 4).map((commit) => (
                <VSurface key={commit.sha} tone="row" elevation="flat" padding="compact" className={styles.gitCommitItem}>
                  <code>{commit.shortSha}</code>
                  <span>{commit.subject}</span>
                </VSurface>
              ))}
            </div>
          </section>
        ) : null}
        {(gitStatus?.files?.length || gitStatus?.truncated || (gitStatus && !gitStatus.available) || (gitStatus?.available && !gitStatus.requiresAttention && !(gitStatus.files?.length))) ? (
          <div className={styles.gitFileList} aria-label={t("gitWorkingTree")}>
            {(gitStatus?.files ?? []).slice(0, 6).map((file) => (
              <VSurface key={`${file.status}-${file.path}`} tone="row" elevation="flat" padding="compact" className={styles.gitFileItem}>
                <VChip tone="neutral">{file.status}</VChip>
                <span>{file.path}</span>
              </VSurface>
            ))}
            {gitStatus?.truncated ? <p className={styles.gitQuietState}>{t("gitTruncated")}</p> : null}
            {gitStatus && gitStatus.available && !gitStatus.requiresAttention && !(gitStatus.files?.length) ? (
              <p className={styles.gitQuietState}>{t("gitNoChanges")}</p>
            ) : null}
            {gitStatus && !gitStatus.available ? (
              <p className={styles.gitQuietState}>{gitStatus.error || t("gitUnavailable")}</p>
            ) : null}
          </div>
        ) : null}
        <section className={styles.gitSection} aria-label={t("gitWorktrees")}>
          <div className={styles.gitSectionHeader}>
            <strong>{t("gitWorktrees")}</strong>
            <VChip tone={gitWorktreeCommits > 0 ? "warning" : "neutral"}>
              {gitStatus?.worktrees?.truncated
                ? t("gitListTruncated")
                : `${gitWorktreeCommits} / ${gitStatus?.worktrees?.total ?? 0}`}
            </VChip>
          </div>
          {gitPendingWorktrees.length ? (
            <div className={styles.gitWorktreeList}>
              {gitPendingWorktrees.slice(0, 5).map((item) => (
                <VSurface
                  key={`${item.path}-${item.branch}`}
                  tone="row"
                  elevation="flat"
                  padding="compact"
                  className={styles.gitWorktreeItem}
                >
                  <strong>{item.branch || item.headRevShort}</strong>
                  <span>{`+${item.aheadMain} / -${item.behindMain}`}</span>
                  <small>{compactWorktreePath(item.path)}</small>
                </VSurface>
              ))}
            </div>
          ) : (
            <p className={styles.gitQuietState}>{t("gitNoWorktreeCommits")}</p>
          )}
        </section>
      </VSurface>
      <VSurface
        as="section"
        id="utility-file-navigator"
        tone="card"
        elevation="flat"
        padding="compact"
        className={styles.utilityFilePanel}
        ariaLabel={t("files")}
      >
        <VPanelHeader
          headingLevel={3}
          className={styles.utilityFileHeader}
          title={t("files")}
          tooltip={utilityFileNavigatorHint}
          tooltipLabel={t("files")}
        />
        <div className={styles.utilityFileSearch}>
          <Search size={14} aria-hidden="true" />
          <VNativeInput
            value={utilityFileFilter}
            onFocus={requestUtilityFileTree}
            onChange={(event) => {
              requestUtilityFileTree();
              setUtilityFileFilter(event.target.value);
            }}
            placeholder={t("searchFilesPlaceholder")}
            aria-label={t("searchFilesPlaceholder")}
          />
        </div>
        <div className={styles.utilityFileTree}>
          {!fileTreeRequested ? (
            <p className={styles.utilityFileState}>
              {lang === "zh" ? "项目文件未载入。" : "Project files not loaded."}
            </p>
          ) : fileTreeQuery.isError ? (
            <p className={styles.utilityFileState}>{t("loadFailed")}</p>
          ) : fileTreeQuery.isPending && !fileTreeQuery.data ? (
            <p className={styles.utilityFileState}>{t("loadingFiles")}</p>
          ) : utilityFilteredFileTree.length === 0 ? (
            <p className={styles.utilityFileState}>{t("noFileMatches")}</p>
          ) : (
            renderUtilityFileTree(utilityFilteredFileTree, handleUtilityOpenFile, utilityActiveFilePath)
          )}
        </div>
      </VSurface>
    </div>
  );
}
