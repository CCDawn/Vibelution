import { lazy, Suspense, useMemo, useState } from "react";
import { ChevronDown, Ellipsis, FileDiff, Undo2 } from "lucide-react";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  classifyDeliveryFiles,
  mergeConversationFileDeliveries,
  type ConversationChangedFileSummary,
  type ConversationFileDeliveryView,
} from "./conversationFileDeliveryModel";
import { ConversationFileRewindDialog } from "./ConversationFileRewindDialog";
import { ConversationPatchDiff } from "./ConversationPatchDiff";
import { VButton, VDialog, VDropdownMenu, VSurface } from "../vui";
import styles from "./ConversationFileDeliveries.styles";

const FilePreview = lazy(() => import("../preview/FilePreview").then((module) => ({ default: module.FilePreview })));

const STATE_PRESENTATION: Record<string, { zh: string; en: string }> = {
  created: { zh: "新建", en: "New" },
  modified: { zh: "修改", en: "Modified" },
};

function FileLineCounts({ additions, deletions, language }: {
  additions: number;
  deletions: number;
  language: "zh" | "en";
}) {
  return (
    <span className={styles.diffStat}
      title={language === "zh" ? "本轮净行数变化" : "Net line-count change in this turn"}
      aria-label={language === "zh" ? `净增 ${additions} 行，净减 ${deletions} 行` : `${additions} net lines added, ${deletions} net lines removed`}>
      <span className={styles.additions}>+{additions}</span>{" "}
      <span className={styles.deletions}>−{deletions}</span>
    </span>
  );
}

export function ConversationFileDeliveries({ cells, language, onContinue, changedFiles, sessionId, turnId }: {
  cells: readonly CodexTranscriptCell[];
  language: "zh" | "en";
  onContinue?: (path: string) => void;
  /** Disk-truth per-turn summary (`metadata.changedFiles`); absent → transcript extraction only. */
  changedFiles?: readonly ConversationChangedFileSummary[];
  /** Session/turn anchors for the rewind flow; both required to expose the entry. */
  sessionId?: string;
  turnId?: string;
}) {
  const { files, patches } = useMemo(() => mergeConversationFileDeliveries(cells, changedFiles), [cells, changedFiles]);
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [rewindOpen, setRewindOpen] = useState(false);
  const { project, workspace } = useMemo(() => classifyDeliveryFiles(files, changedFiles), [files, changedFiles]);
  const file: ConversationFileDeliveryView | undefined = files.find((entry) => entry.path === selected);
  const rewindAvailable = Boolean(sessionId && turnId && changedFiles?.length);
  const zh = language === "zh";
  if (!files.length) return null;

  // +/− only ever aggregate project files; workspace scripts stay count-only.
  const projectAdditions = project.reduce((sum, entry) => sum + (entry.additions ?? 0), 0);
  const projectDeletions = project.reduce((sum, entry) => sum + (entry.deletions ?? 0), 0);
  const projectStatsKnown = project.length > 0
    && project.every((entry) => entry.additions != null && entry.deletions != null);
  const summaryLabel = project.length
    ? (zh ? `已编辑 ${project.length} 个文件` : `Edited ${project.length} ${project.length === 1 ? "file" : "files"}`)
    : (zh ? `工作区脚本 · ${workspace.length}` : `Workspace scripts · ${workspace.length}`);
  const orderedFiles = [...project, ...workspace];
  const visibleFiles = expanded ? orderedFiles : orderedFiles.slice(0, 3);
  const workspacePaths = new Set(workspace.map((entry) => entry.path));
  const toggle = () => setExpanded((value) => !value);

  const renderFile = (entry: ConversationFileDeliveryView) => {
    const separator = Math.max(entry.path.lastIndexOf("/"), entry.path.lastIndexOf("\\"));
    const folder = entry.path.slice(0, separator + 1);
    const name = entry.path.slice(separator + 1);
    const workspaceFile = workspacePaths.has(entry.path);
    const menuItems = entry.deleted ? [] : [
      ...(entry.content !== undefined ? [{ id: "preview", label: zh ? "查看内容" : "View content", onSelect: () => setSelected(entry.path) }] : []),
      ...(onContinue ? [{ id: "continue", label: zh ? "继续修改" : "Continue editing", onSelect: () => onContinue(entry.path) }] : []),
    ];
    return (
      <li key={entry.path} className={styles.fileRow} data-file-delivery-path={entry.path}>
        <span className={styles.path} title={entry.path}>
          <span className={styles.folder}>{folder}</span><span className={styles.fileName}>{name}</span>
        </span>
        <span className={styles.rowMeta}>
          {workspaceFile ? <span className={styles.workspaceNote}>{zh ? "工作区" : "Workspace"}</span> : null}
          {entry.deleted ? <span className={styles.caption}>{zh ? "已删除" : "Deleted"}</span> : entry.state ? (
            <span className="sr-only">{(STATE_PRESENTATION[entry.state] ?? STATE_PRESENTATION.modified)[language]}</span>
          ) : null}
          {menuItems.length ? <VDropdownMenu align="end" items={menuItems} trigger={(
            <VButton variant="ghost" isIconOnly icon={<Ellipsis size={14} aria-hidden="true" />}
              className={styles.rowMenu} aria-label={zh ? `文件操作：${name}` : `File actions: ${name}`} />
          )} /> : null}
          {entry.additions != null || entry.deletions != null ? (
            <FileLineCounts additions={entry.additions ?? 0} deletions={entry.deletions ?? 0} language={language} />
          ) : null}
        </span>
      </li>
    );
  };

  return (
    <VSurface as="section" tone="panel" padding="none" className={styles.root}
      aria-label={zh ? "本轮文件" : "Files from this turn"} data-conversation-file-deliveries="true">
      <header className={styles.summaryRow} data-file-deliveries-summary="true">
        <span className={styles.headerIcon}><FileDiff size={22} aria-hidden="true" /></span>
        <div className={styles.headerCopy}>
          <p className={styles.title}>{summaryLabel}</p>
          {projectStatsKnown ? <FileLineCounts additions={projectAdditions} deletions={projectDeletions} language={language} /> : null}
          {project.length && workspace.length ? (
            <span className={styles.workspaceNote}>{zh ? `另有 ${workspace.length} 个工作区脚本` : `and ${workspace.length} workspace scripts`}</span>
          ) : null}
        </div>
        <div className={styles.headerActions}>
          {rewindAvailable ? (
            <VButton
              variant="ghost"
              className={styles.headerButton}
              aria-label={zh ? "回退本轮文件" : "Rewind this turn's files"}
              tooltip={zh ? "预览并撤销本轮文件改动" : "Preview and rewind this turn's file changes"}
              trailingIcon={<Undo2 size={14} aria-hidden="true" />}
              onPress={() => setRewindOpen(true)}
            >
              {zh ? "撤销" : "Undo"}
            </VButton>
          ) : null}
          <VButton variant="secondary" className={styles.viewButton} isDisabled={!patches.length}
            disabledReason={zh ? "没有可查看的补丁记录" : "No recorded patches to view"}
            onPress={() => setShowDiff(true)}>{zh ? "查看变更" : "View changes"}</VButton>
        </div>
      </header>
      <ul className={styles.fileList} data-file-deliveries-list="true">{visibleFiles.map(renderFile)}</ul>
      {orderedFiles.length > 3 ? (
        <VButton variant="ghost" contentLayout="plain" className={styles.moreButton} aria-expanded={expanded}
          trailingIcon={<ChevronDown size={16} aria-hidden="true" className={expanded ? styles.chevronExpanded : styles.chevron} />}
          onPress={toggle}>
          {expanded ? (zh ? "收起文件" : "Show fewer files")
            : (zh ? `再显示 ${orderedFiles.length - 3} 个文件` : `Show ${orderedFiles.length - 3} more files`)}
        </VButton>
      ) : null}
      {sessionId && turnId && changedFiles?.length ? (
        <ConversationFileRewindDialog
          open={rewindOpen}
          sessionId={sessionId}
          turnId={turnId}
          language={language}
          onOpenChange={setRewindOpen}
        />
      ) : null}
      {file?.content !== undefined ? <VDialog data-vui="conversation-file-dialog" open onOpenChange={(open) => { if (!open) setSelected(null); }} title={file.path}
        description={zh ? "本轮写入内容；不代表磁盘上的最新文件。" : "Content written in this turn; not the latest file on disk."}
        size="xl" className={styles.dialog} contentClassName={styles.dialogContent}
        footer={onContinue ? <VButton onPress={() => { setSelected(null); onContinue(file.path); }}>{zh ? "继续修改此文件" : "Continue editing this file"}</VButton> : undefined}>
        <div className={styles.preview}>
          <Suspense fallback={<p role="status">{zh ? "正在加载…" : "Loading…"}</p>}>
            <FilePreview file={{ path: file.path, content: file.content, language: /\.html?$/i.test(file.path) ? "html" : "text", truncated: false }} changed={false} sourceLabel={zh ? "本轮写入" : "Turn snapshot"} />
          </Suspense>
        </div>
      </VDialog> : null}
      {showDiff ? <VDialog data-vui="conversation-patch-dialog" open onOpenChange={setShowDiff} title={zh ? "本轮补丁" : "This turn’s patches"}
        description={zh ? "仅包含成功工具调用中记录的补丁，按执行顺序展示；不等于整轮净差异。" : "Recorded patches from successful calls, in execution order; not a net diff."}
        size="xl" className={styles.dialog}>
        {patches.map((patch) => <ConversationPatchDiff key={patch.id} patchText={patch.text} language={language} />)}
      </VDialog> : null}
    </VSurface>
  );
}
