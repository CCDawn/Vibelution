import { lazy, Suspense, useMemo, useState } from "react";
import { FileText } from "lucide-react";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { collectConversationFileDeliveries, type ConversationFileDelivery } from "./conversationFileDeliveryModel";
import { ConversationPatchDiff } from "./ConversationPatchDiff";
import { VButton, VDialog, VSurface } from "../vui";
import styles from "./ConversationFileDeliveries.styles";

const FilePreview = lazy(() => import("../preview/FilePreview").then((module) => ({ default: module.FilePreview })));

export function ConversationFileDeliveries({ cells, language, onContinue }: {
  cells: readonly CodexTranscriptCell[];
  language: "zh" | "en";
  onContinue?: (path: string) => void;
}) {
  const { files, patches } = useMemo(() => collectConversationFileDeliveries(cells), [cells]);
  const [selected, setSelected] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const file: ConversationFileDelivery | undefined = files.find((entry) => entry.path === selected);
  const zh = language === "zh";
  if (!files.length) return null;
  return (
    <section className={styles.root} aria-label={zh ? "本轮文件" : "Files from this turn"} data-conversation-file-deliveries="true">
      <p className={styles.caption}>{zh ? `本轮文件 · ${files.length}` : `Files from this turn · ${files.length}`}</p>
      {files.map((entry) => (
        <VSurface key={entry.path} tone="card" className={styles.card}>
          <FileText size={16} aria-hidden="true" />
          <span className={styles.path} title={entry.path}>{entry.path}</span>
          {entry.deleted ? <span className={styles.caption}>{zh ? "已删除" : "Deleted"}</span> : (
            <div className={styles.actions}>
              {entry.content !== undefined ? <VButton onPress={() => setSelected(entry.path)}>{zh ? "查看内容" : "View content"}</VButton> : null}
              {onContinue ? <VButton variant="ghost" onPress={() => onContinue(entry.path)}>{zh ? "继续修改" : "Continue editing"}</VButton> : null}
            </div>
          )}
        </VSurface>
      ))}
      {patches.length ? <VButton variant="ghost" onPress={() => setShowDiff(true)}>{zh ? "查看本轮补丁" : "View this turn’s patches"}</VButton> : null}
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
