import { lazy, Suspense, useMemo, useState } from "react";
import { ChevronRight, FileText } from "lucide-react";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  classifyDeliveryFiles,
  mergeConversationFileDeliveries,
  type ConversationChangedFileSummary,
  type ConversationFileDeliveryView,
} from "./conversationFileDeliveryModel";
import { ConversationFileRewindDialog } from "./ConversationFileRewindDialog";
import { ConversationPatchDiff } from "./ConversationPatchDiff";
import { VButton, VDialog, VSurface } from "../vui";
import styles from "./ConversationFileDeliveries.styles";

const FilePreview = lazy(() => import("../preview/FilePreview").then((module) => ({ default: module.FilePreview })));

const STATE_PRESENTATION: Record<string, { zh: string; en: string }> = {
  created: { zh: "新建", en: "New" },
  modified: { zh: "修改", en: "Modified" },
};

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
  const summaryLabel = project.length
    ? (zh ? `本轮文件 · ${project.length}` : `Files from this turn · ${project.length}`)
    : (zh ? `工作区脚本 · ${workspace.length}` : `Workspace scripts · ${workspace.length}`);
  const toggle = () => setExpanded((value) => !value);

  const renderCard = (entry: ConversationFileDeliveryView, muted: boolean) => (
    <VSurface key={entry.path} tone="card" className={muted ? styles.cardMuted : styles.card}>
      <FileText size={16} aria-hidden="true" />
      <span className={styles.path} title={entry.path}>{entry.path}</span>
      {entry.additions != null || entry.deletions != null ? (
        <span className={styles.diffStat}>{`+${entry.additions ?? 0} −${entry.deletions ?? 0}`}</span>
      ) : null}
      {!entry.deleted && entry.state ? (
        <span className={styles.caption}>
          {zh
            ? (STATE_PRESENTATION[entry.state] ?? STATE_PRESENTATION.modified).zh
            : (STATE_PRESENTATION[entry.state] ?? STATE_PRESENTATION.modified).en}
        </span>
      ) : null}
      {entry.deleted ? <span className={styles.caption}>{zh ? "已删除" : "Deleted"}</span> : (
        <div className={styles.actions}>
          {entry.content !== undefined ? <VButton onPress={() => setSelected(entry.path)}>{zh ? "查看内容" : "View content"}</VButton> : null}
          {onContinue ? <VButton variant="ghost" onPress={() => onContinue(entry.path)}>{zh ? "继续修改" : "Continue editing"}</VButton> : null}
        </div>
      )}
    </VSurface>
  );

  return (
    <section className={styles.root} aria-label={zh ? "本轮文件" : "Files from this turn"} data-conversation-file-deliveries="true">
      <div
        className={styles.summaryRow}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        data-file-deliveries-summary="true"
        onClick={toggle}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
          }
        }}
      >
        <ChevronRight size={14} aria-hidden="true" className={expanded ? styles.chevronExpanded : styles.chevron} />
        <p className={styles.caption}>{summaryLabel}</p>
        {project.length ? <span className={styles.diffStat}>{`+${projectAdditions} −${projectDeletions}`}</span> : null}
        {project.length && workspace.length ? (
          <span className={styles.workspaceNote}>{zh ? `另有 ${workspace.length} 个工作区脚本` : `and ${workspace.length} workspace scripts`}</span>
        ) : null}
        <div className={styles.headerActions} onClick={(event) => event.stopPropagation()}>
          {rewindAvailable ? (
            <VButton
              variant="ghost"
              onPress={(event) => {
                event.stopPropagation();
                setRewindOpen(true);
              }}
            >
              {zh ? "回退本轮文件" : "Rewind files"}
            </VButton>
          ) : null}
        </div>
      </div>
      {expanded ? (
        <div className={styles.fileList}>
          {project.length ? (
            <div className={styles.group}>
              <p className={styles.groupCaption}>{zh ? `项目改动 · ${project.length}` : `Project changes · ${project.length}`}</p>
              {project.map((entry) => renderCard(entry, false))}
            </div>
          ) : null}
          {workspace.length ? (
            <div className={styles.group}>
              <p className={styles.groupCaption}>{zh ? `工作区脚本 · ${workspace.length}` : `Workspace scripts · ${workspace.length}`}</p>
              <p className={styles.groupNote}>{zh ? "Agent 工作区内的文件。" : "Files inside the agent workspace."}</p>
              {workspace.map((entry) => renderCard(entry, true))}
            </div>
          ) : null}
          {patches.length ? <VButton variant="ghost" onPress={() => setShowDiff(true)}>{zh ? "查看本轮补丁" : "View this turn’s patches"}</VButton> : null}
        </div>
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
    </section>
  );
}
