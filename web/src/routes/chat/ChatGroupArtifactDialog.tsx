import { useEffect, useMemo, useState, type ComponentProps } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";

import { fetchFileContent } from "../../api/files";
import {
  listDevTeamTaskChanges,
  listDevTeamTasks,
  type DevTeamTask,
  type DevTeamTaskChange,
  type DevTeamTaskChanges,
} from "../../api/devTeamTasks";
import type { FileContent } from "../../api/types";
import { ChatFilePreviewPanel } from "./ChatFilePreviewPanel";
import { VButton, VDialog } from "../../components/vui";
import styles from "./ChatGroupArtifactDialog.styles";

export type ChatGroupArtifactDialogProps = {
  teamId: string;
  taskIds: string[];
  lang: "zh" | "en";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: ComponentProps<typeof VDialog>["onCloseAutoFocus"];
};

type SafeTaskChange = DevTeamTaskChange & {
  path: string;
  projectPath: string;
};

type SelectedChange = {
  taskId: string;
  path: string;
};

function taskListKey(teamId: string) {
  return ["teams", teamId, "dev-tasks"] as const;
}

function taskChangesKey(teamId: string, taskId: string) {
  return ["teams", teamId, "dev-tasks", taskId, "changes"] as const;
}

function taskWorkspaceSlug(workspacePath: string, workspaceBranch: string) {
  const pathMatch = /^\.worktrees\/([a-z0-9]+(?:-[a-z0-9]+)*)$/.exec(String(workspacePath || "").trim());
  if (!pathMatch || String(workspaceBranch || "").trim() !== `codex/${pathMatch[1]}`) {
    return null;
  }
  return pathMatch[1];
}

function safeRelativeChangePath(value: string) {
  const path = String(value || "").trim();
  if (
    !path
    || path.includes("\\")
    || path.includes("\0")
    || path.includes(":")
    || path.startsWith("/")
    || /^[a-z]:/i.test(path)
  ) {
    return null;
  }
  const segments = path.split("/");
  if (segments.some((segment) => !segment || segment === "." || segment === "..")) {
    return null;
  }
  return segments.join("/");
}

/** Build a project-relative file path only from a verified task workspace and API change path. */
export function resolveTaskWorkspaceFilePath(
  changePath: string,
  workspacePath: string,
  workspaceBranch: string,
) {
  const slug = taskWorkspaceSlug(workspacePath, workspaceBranch);
  const relativePath = safeRelativeChangePath(changePath);
  if (!slug || !relativePath) {
    return null;
  }
  return `.worktrees/${slug}/${relativePath}`;
}

function changeStatusLabel(status: string, lang: "zh" | "en") {
  const labels: Record<string, { zh: string; en: string }> = {
    added: { zh: "新增", en: "Added" },
    modified: { zh: "修改", en: "Modified" },
    deleted: { zh: "删除", en: "Deleted" },
    untracked: { zh: "未跟踪", en: "Untracked" },
  };
  return labels[status]?.[lang] || status || (lang === "zh" ? "改动" : "Changed");
}

function normalizeTaskChange(
  change: DevTeamTaskChange,
  slug: string,
): SafeTaskChange | null {
  const path = safeRelativeChangePath(change?.path);
  if (!path) {
    return null;
  }
  return {
    ...change,
    path,
    projectPath: `.worktrees/${slug}/${path}`,
  };
}

function changeCount(changes: DevTeamTaskChanges | undefined) {
  if (!changes || !Array.isArray(changes.changes)) {
    return 0;
  }
  return changes.changes.length + Math.max(0, Number(changes.truncated) || 0);
}

export function ChatGroupArtifactDialog({
  teamId,
  taskIds,
  lang,
  open,
  onOpenChange,
  onCloseAutoFocus,
}: ChatGroupArtifactDialogProps) {
  const zh = lang === "zh";
  const normalizedTeamId = String(teamId || "").trim();
  const normalizedTaskIds = useMemo(
    () => [...new Set(taskIds.map((taskId) => String(taskId || "").trim()).filter(Boolean))],
    [taskIds],
  );
  const enabled = open && Boolean(normalizedTeamId) && normalizedTaskIds.length > 0;
  const tasksQuery = useQuery({
    queryKey: taskListKey(normalizedTeamId),
    queryFn: ({ signal }) => listDevTeamTasks(normalizedTeamId, { signal }),
    enabled,
    staleTime: 5_000,
  });
  const tasksMatchTeam = tasksQuery.data?.teamId === normalizedTeamId;
  const tasksById = new Map<string, DevTeamTask>(
    (tasksMatchTeam ? tasksQuery.data?.tasks ?? [] : [])
      .map((task) => [String(task.id || "").trim(), task]),
  );
  const changesQueries = useQueries({
    queries: normalizedTaskIds.map((taskId) => ({
      queryKey: taskChangesKey(normalizedTeamId, taskId),
      queryFn: ({ signal }) => listDevTeamTaskChanges(normalizedTeamId, taskId, { signal }),
      enabled: enabled && tasksMatchTeam && tasksById.has(taskId),
      staleTime: 5_000,
    })),
  });
  const [selectedChange, setSelectedChange] = useState<SelectedChange | null>(null);
  useEffect(() => {
    if (!open) {
      setSelectedChange(null);
    }
  }, [open]);

  const sections = normalizedTaskIds.map((taskId, index) => {
    const task = tasksById.get(taskId);
    const changesQuery = changesQueries[index];
    const changes = changesQuery?.data;
    const workspaceSlug = task
      ? taskWorkspaceSlug(String(task.workspacePath || ""), String(task.workspaceBranch || ""))
      : null;
    const rawChanges = Array.isArray(changes?.changes) ? changes.changes : [];
    const normalizedChanges = workspaceSlug
      ? rawChanges.map((change) => normalizeTaskChange(change, workspaceSlug))
      : [];
    const hasUnsafePath = Boolean(workspaceSlug && normalizedChanges.some((change) => !change));
    const safeChanges = normalizedChanges.filter((change): change is SafeTaskChange => Boolean(change));
    return {
      taskId,
      task,
      changesQuery,
      changes,
      workspaceSlug,
      hasUnsafePath,
      safeChanges,
    };
  });
  const selectedSection = selectedChange
    ? sections.find((section) => section.taskId === selectedChange.taskId)
    : undefined;
  const selectedCandidate = selectedChange
    ? selectedSection?.safeChanges.find((change) => change.path === selectedChange.path)
    : undefined;
  const activeChange = open
    && tasksMatchTeam
    && !tasksQuery.isError
    && Boolean(selectedSection?.task)
    && !selectedSection?.changesQuery?.isError
    && Boolean(selectedSection?.changes?.available && selectedSection.changes.workspace)
    && Boolean(selectedSection?.workspaceSlug)
    && !selectedSection?.hasUnsafePath
    && String(selectedCandidate?.status || "").trim().toLowerCase() !== "deleted"
    ? selectedCandidate
    : undefined;
  useEffect(() => {
    if (selectedChange && !activeChange) {
      setSelectedChange(null);
    }
  }, [activeChange, selectedChange]);
  const previewPath = activeChange?.projectPath || "";
  const fileQuery = useQuery<FileContent>({
    queryKey: ["files", "content", previewPath],
    queryFn: () => fetchFileContent(previewPath),
    enabled: open && Boolean(previewPath),
    staleTime: 0,
  });
  const text = (zhText: string, enText: string) => (zh ? zhText : enText);
  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setSelectedChange(null);
    }
    onOpenChange(nextOpen);
  };

  return (
    <VDialog
      open={open}
      onOpenChange={handleOpenChange}
      onCloseAutoFocus={onCloseAutoFocus}
      title={text("当前任务改动", "Current task changes")}
      description={text("任务工作区当前状态，不是历史版本。", "Current task workspace state, not a historical version.")}
      size="lg"
      contentClassName={styles.artifactDialog}
      aria-label={text("当前任务改动", "Current task changes")}
      data-vui="chat-group-artifact-dialog"
    >
      <div className={styles.body} data-testid="chat-group-artifact-body">
        {!normalizedTeamId ? (
          <p className={styles.state} role="status">{text("缺少团队信息。", "Team information is unavailable.")}</p>
        ) : normalizedTaskIds.length === 0 ? (
          <p className={styles.state} role="status">{text("没有关联任务。", "No linked tasks.")}</p>
        ) : tasksQuery.isLoading ? (
          <p className={styles.state} role="status">{text("正在读取任务…", "Loading tasks…")}</p>
        ) : tasksQuery.isError ? (
          <p className={styles.state} role="alert">{text("任务信息加载失败。", "Could not load task details.")}</p>
        ) : !tasksMatchTeam ? (
          <p className={styles.state} role="alert">{text("团队信息不一致，无法读取任务改动。", "Team identity did not match; task changes could not be loaded.")}</p>
        ) : activeChange ? (
          <>
            <div className={styles.previewHeader}>
              <p className={styles.previewPath} title={activeChange.path}>{activeChange.path}</p>
              <VButton
                type="button"
                variant="secondary"
                density="compact"
                onPress={() => setSelectedChange(null)}
                data-vui="chat-group-artifact-back"
              >
                {text("返回文件列表", "Back to files")}
              </VButton>
            </div>
            <ChatFilePreviewPanel
              changed
              errorMessage={fileQuery.isError ? text("文件预览读取失败。", "Could not load this file preview.") : ""}
              file={fileQuery.isFetching ? undefined : fileQuery.data}
              loadingLabel={text("正在读取文件…", "Loading file…")}
              sourceLabel={text("当前任务工作区", "Current task workspace")}
            />
          </>
        ) : (
          sections.map((section) => {
            const { task, changes, changesQuery, taskId, workspaceSlug, safeChanges, hasUnsafePath } = section;
            const taskLabel = task?.subject || text(`任务 ${taskId}`, `Task ${taskId}`);
            const fileCount = changeCount(changes);
            const changesReady = Boolean(changes?.available && changes.workspace);
            const hideDetails = !workspaceSlug || hasUnsafePath;

            return (
              <section key={taskId} className={styles.task} aria-label={taskLabel}>
                <header className={styles.taskHeading}>
                  <strong className="min-w-0 break-words">{taskLabel}</strong>
                  {!task?.subject ? <code className={styles.taskId}>{taskId}</code> : null}
                </header>
                {!task ? (
                  <p className={styles.state} role="status">{text("任务已不存在。", "This task is no longer available.")}</p>
                ) : changesQuery?.isLoading ? (
                  <p className={styles.state} role="status">{text("正在读取当前改动…", "Loading current changes…")}</p>
                ) : changesQuery?.isError ? (
                  <p className={styles.state} role="alert">{text("当前改动读取失败。", "Could not load current changes.")}</p>
                ) : !changes?.available ? (
                  <p className={styles.state} role="status">{text("当前改动暂不可用。", "Current changes are unavailable.")}</p>
                ) : !changes.workspace ? (
                  <p className={styles.state} role="status">{text("任务尚无工作区。", "This task has no workspace yet.")}</p>
                ) : hideDetails ? (
                  <p className={styles.note} role="status">
                    {text(
                      hasUnsafePath
                        ? `发现 ${fileCount} 项改动，但文件路径无法验证，明细已隐藏。`
                        : `发现 ${fileCount} 项改动，但工作区信息无法验证，明细已隐藏。`,
                      hasUnsafePath
                        ? `${fileCount} changes were found, but file paths could not be verified and are hidden.`
                        : `${fileCount} changes were found, but the workspace could not be verified and details are hidden.`,
                    )}
                  </p>
                ) : safeChanges.length === 0 ? (
                  <p className={styles.state} role="status">{text("当前没有文件改动。", "There are no current file changes.")}</p>
                ) : (
                  <>
                    <ul className={styles.fileList}>
                      {safeChanges.map((change, changeIndex) => {
                        const status = String(change.status || "").trim().toLowerCase();
                        const label = changeStatusLabel(status, lang);
                        return (
                          <li
                            className={styles.fileRow}
                            key={`${status}:${change.path}:${changeIndex}`}
                            data-status={status}
                          >
                            <span className={styles.fileStatus} data-status={status}>{label}</span>
                            {status === "deleted" ? (
                              <span className={styles.filePath}>{change.path}</span>
                            ) : (
                              <VButton
                                type="button"
                                variant="ghost"
                                density="compact"
                                contentLayout="plain"
                                className={styles.fileButton}
                                aria-label={text(`预览 ${change.path}`, `Preview ${change.path}`)}
                                onPress={() => setSelectedChange({ taskId, path: change.path })}
                                data-vui="chat-group-artifact-file"
                              >
                                <span className={styles.filePath}>{change.path}</span>
                              </VButton>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                    {Number(changes?.truncated) > 0 ? (
                      <p className={styles.note}>
                        {text(`还有 ${Number(changes.truncated)} 个文件未列出。`, `${Number(changes.truncated)} more files are not listed.`)}
                      </p>
                    ) : null}
                  </>
                )}
              </section>
            );
          })
        )}
      </div>
    </VDialog>
  );
}
