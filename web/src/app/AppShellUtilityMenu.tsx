import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { ExternalLink, FolderTree, GitBranch, ScrollText, Search } from "lucide-react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { FileTreeNode, GitStatusSummary } from "../api/types";
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
      <button
        key={node.path}
        type="button"
        className={active ? `${styles.utilityFileButton} ${styles.utilityFileButtonActive}` : styles.utilityFileButton}
        onClick={() => onOpenFile(node.path)}
        title={node.path}
      >
        <span>{node.name}</span>
        <small>{node.path}</small>
      </button>
    );
  });
}

export function AppShellUtilityMenu({ lang, t, frontendVisible, onClose }: AppShellUtilityMenuProps) {
  const navigate = useNavigate();
  const [utilityFileFilter, setUtilityFileFilter] = useState("");
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
    staleTime: 8_000,
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
  const gitTone: SystemStatusTone = gitAvailable ? (gitDirty ? "caution" : "running") : "idle";
  const gitBranch = gitStatus?.branch || gitStatus?.headRevShort || "-";
  const gitValue = gitAvailable
    ? gitDirty
      ? `${gitStatus?.counts.total ?? 0}`
      : t("gitClean")
    : gitStatusQuery.isPending
      ? t("gitChecking")
      : t("gitUnavailable");
  const gitTitle = gitAvailable
    ? `${t("gitStatus")}: ${gitStatus?.summary ?? ""}`
    : gitStatus?.error || t("gitUnavailable");
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
        <button
          type="button"
          className={styles.utilityButton}
          role="menuitem"
          onClick={() => document.getElementById("utility-file-navigator")?.scrollIntoView({ block: "nearest" })}
        >
          <FolderTree size={16} />
          <span>{t("files")}</span>
        </button>
      </div>
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
            onChange={(event) => setUtilityFileFilter(event.target.value)}
            placeholder={t("searchFilesPlaceholder")}
          />
        </div>
        <div className={styles.utilityFileTree}>
          {fileTreeQuery.isError ? (
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
      <div className={styles.gitMiniPanel} aria-label={t("gitStatusGuide")} title={gitTitle}>
        <div className={styles.gitMiniHeader}>
          <div className={styles.gitChip}>
            <GitBranch size={14} />
            <span className={`${styles.statusDot} ${styles[`status_${gitTone}`]}`} />
            <span className={styles.gitBranchName}>{gitBranch}</span>
            <strong className={styles.gitCount}>{gitValue}</strong>
          </div>
          <span>{gitStatus?.summary || t("gitStatusGuideHint")}</span>
        </div>
        <div className={styles.gitMetaGrid}>
          <span>{t("gitBranch")}</span>
          <strong>{gitBranch}</strong>
          <span>{t("gitUpstream")}</span>
          <strong>{gitStatus?.upstream?.name || gitStatus?.upstream?.remote || t("gitNoUpstream")}</strong>
        </div>
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
          {gitStatus && gitStatus.available && !gitStatus.files.length ? <p>{t("gitNoChanges")}</p> : null}
          {gitStatus && !gitStatus.available ? <p>{gitStatus.error || t("gitUnavailable")}</p> : null}
        </div>
      </div>
    </div>
  );
}
