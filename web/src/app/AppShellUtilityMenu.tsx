import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { ExternalLink, FolderTree, GitBranch, ScrollText, Search } from "lucide-react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { FileTreeNode, GitStatusSummary } from "../api/types";
import { VButton } from "../components/vui";
import type { Language, ShellTranslationKey } from "../i18n/shellDictionary";
import { useChatWorkbenchStore } from "../store/chatWorkbenchStore";
import { resolvePollingInterval } from "./pollingPolicy";
import type { SystemStatusTone } from "./systemStatus";
import styles from "./AppShell.module.css";

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
        className={active ? `${styles.utilityFileButton} ${styles.utilityFileButtonActive}` : styles.utilityFileButton}
        onPress={() => onOpenFile(node.path)}
        title={node.path}
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

export function AppShellUtilityMenu({ lang, t, frontendVisible, onClose }: AppShellUtilityMenuProps) {
  const navigate = useNavigate();
  const [utilityFileFilter, setUtilityFileFilter] = useState("");
  const [fileTreeRequested, setFileTreeRequested] = useState(false);
  const activeSessionId = useChatWorkbenchStore((state) => state.activeSessionId);
  const activeSessionWorkspace = useChatWorkbenchStore((state) =>
    state.activeSessionId ? state.sessionWorkspaces[state.activeSessionId] : undefined,
  );
  const openPreviewTab = useChatWorkbenchStore((state) => state.openPreviewTab);
  const gitRefetchInterval = resolvePollingInterval(frontendVisible, 6_000, { backgroundMs: 60_000 });
  const gitStatusQuery = useQuery({
    queryKey: queryKeys.gitStatus(),
    queryFn: () => fetchJson<GitStatusSummary>("/api/git/status"),
    refetchInterval: gitRefetchInterval,
    refetchIntervalInBackground: false,
  });
  const fileTreeQuery = useQuery({
    queryKey: queryKeys.fileTree(),
    queryFn: () => fetchJson<FileTreeNode[]>("/api/files/tree"),
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
      role="menu"
      aria-label={t("topUtilityMenu")}
    >
      <div className={styles.utilityPanelHeader}>
        <strong>{t("topUtilityMenu")}</strong>
        <span>{t("topUtilityMenuHint")}</span>
      </div>
      <div className={styles.utilityButtonGrid}>
        <a href="/launcher" target="_blank" rel="noreferrer" className={styles.utilityButton} role="menuitem" onClick={onClose}>
          <ExternalLink size={16} />
          <span>{lang === "zh" ? "启动器" : "Launcher"}</span>
        </a>
        <NavLink to="/logs" className={({ isActive }) => isActive ? `${styles.utilityButton} ${styles.utilityButtonActive}` : styles.utilityButton} role="menuitem" onClick={onClose}>
          <ScrollText size={16} />
          <span>{t("navLogs")}</span>
        </NavLink>
        <NavLink to="/git" className={({ isActive }) => isActive ? `${styles.utilityButton} ${styles.utilityButtonActive}` : styles.utilityButton} role="menuitem" onClick={onClose}>
          <GitBranch size={16} />
          <span>{t("navGit")}</span>
        </NavLink>
        <VButton
          type="button"
          className={styles.utilityButton}
          role="menuitem"
          icon={<FolderTree size={16} />}
          onPress={() => {
            requestUtilityFileTree();
            window.requestAnimationFrame(() => document.getElementById("utility-file-navigator")?.scrollIntoView({ block: "nearest" }));
          }}
        >
          <span>{t("files")}</span>
        </VButton>
      </div>
      <section className={styles.gitMiniPanel} aria-label={t("gitStatusGuide")} title={gitTitle}>
        <div className={styles.gitMiniHeader}>
          <div className={styles.gitChip}>
            <GitBranch size={14} />
            <span className={`${styles.statusDot} ${styles[`status_${gitTone}`]}`} />
            <span className={styles.gitBranchName}>{gitBranch}</span>
            <strong className={styles.gitCount}>{gitValue}</strong>
          </div>
          <div className={styles.gitHeadline}>
            <strong>{gitHeroLabel}</strong>
            <span>{gitStatus?.summary || t("gitStatusGuideHint")}</span>
          </div>
        </div>
        <div className={styles.gitSignalGrid}>
          <span>
            <strong>{gitLocalCommits}</strong>
            {t("gitLocalAhead")}
          </span>
          <span>
            <strong>{gitBehind}</strong>
            {t("gitRemoteBehind")}
          </span>
          <span>
            <strong>{gitWorktreeCommits}</strong>
            {t("gitWorktreesPending")}
          </span>
          <span>
            <strong>{gitDirtyCount}</strong>
            {t("gitWorkingTree")}
          </span>
        </div>
        <div className={styles.gitMetaGrid}>
          <span>{t("gitBranch")}</span>
          <strong>{gitBranch}</strong>
          <span>{t("gitUpstream")}</span>
          <strong>{gitStatus?.upstream?.name || gitStatus?.upstream?.remote || t("gitNoUpstream")}</strong>
          <span>{t("gitWorktrees")}</span>
          <strong>{gitWorktreeCommits} / {gitStatus?.worktrees?.total ?? 0}</strong>
        </div>
        {gitStatus?.localCommits?.commits?.length ? (
          <section className={styles.gitSection} aria-label={t("gitLocalCommits")}>
            <div className={styles.gitSectionHeader}>
              <strong>{t("gitLocalCommits")}</strong>
              <span>{gitStatus.localCommits.truncated ? t("gitListTruncated") : `${gitStatus.localCommits.total}`}</span>
            </div>
            <div className={styles.gitCommitList}>
              {gitStatus.localCommits.commits.slice(0, 4).map((commit) => (
                <div key={commit.sha} className={styles.gitCommitItem}>
                  <code>{commit.shortSha}</code>
                  <span>{commit.subject}</span>
                </div>
              ))}
            </div>
          </section>
        ) : null}
        <div className={styles.gitCountGrid}>
          <span>
            <strong>{gitStatus?.counts.staged ?? 0}</strong>
            {t("gitStaged")}
          </span>
          <span>
            <strong>{gitStatus?.counts.unstaged ?? 0}</strong>
            {t("gitUnstaged")}
          </span>
          <span>
            <strong>{gitStatus?.counts.untracked ?? 0}</strong>
            {t("gitUntracked")}
          </span>
          <span>
            <strong>{gitStatus?.counts.deleted ?? 0}</strong>
            {t("gitDeleted")}
          </span>
        </div>
        <div className={styles.gitFileList}>
          {(gitStatus?.files ?? []).slice(0, 6).map((file) => (
            <div key={`${file.status}-${file.path}`} className={styles.gitFileItem}>
              <code>{file.status}</code>
              <span>{file.path}</span>
            </div>
          ))}
          {gitStatus?.truncated ? <p>{t("gitTruncated")}</p> : null}
          {gitStatus && gitStatus.available && !gitStatus.requiresAttention ? <p>{t("gitNoChanges")}</p> : null}
          {gitStatus && !gitStatus.available ? <p>{gitStatus.error || t("gitUnavailable")}</p> : null}
        </div>
        <section className={styles.gitSection} aria-label={t("gitWorktrees")}>
          <div className={styles.gitSectionHeader}>
            <strong>{t("gitWorktrees")}</strong>
            <span>{gitStatus?.worktrees?.truncated ? t("gitListTruncated") : `${gitWorktreeCommits} / ${gitStatus?.worktrees?.total ?? 0}`}</span>
          </div>
          {gitPendingWorktrees.length ? (
            <div className={styles.gitWorktreeList}>
              {gitPendingWorktrees.slice(0, 5).map((item) => (
                <div key={`${item.path}-${item.branch}`} className={styles.gitWorktreeItem}>
                  <strong>{item.branch || item.headRevShort}</strong>
                  <span>{`+${item.aheadMain} / -${item.behindMain}`}</span>
                  <small>{compactWorktreePath(item.path)}</small>
                </div>
              ))}
            </div>
          ) : (
            <p className={styles.gitQuietState}>{t("gitNoWorktreeCommits")}</p>
          )}
        </section>
      </section>
      <section id="utility-file-navigator" className={styles.utilityFilePanel} aria-label={t("files")}>
        <div className={styles.utilityFileHeader}>
          <div>
            <strong>{t("files")}</strong>
            <span>
              {activeSessionId
                ? (lang === "zh" ? "点击文件会在当前会话工作区打开预览。" : "Click a file to open it in the current chat workspace.")
                : (lang === "zh" ? "先进入会话后可打开文件预览。" : "Open a chat first to preview files.")}
            </span>
          </div>
        </div>
        <div className={styles.utilityFileSearch}>
          <Search size={14} />
          <input
            value={utilityFileFilter}
            onFocus={requestUtilityFileTree}
            onChange={(event) => {
              requestUtilityFileTree();
              setUtilityFileFilter(event.target.value);
            }}
            placeholder={t("searchFilesPlaceholder")}
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
      </section>
    </div>
  );
}
