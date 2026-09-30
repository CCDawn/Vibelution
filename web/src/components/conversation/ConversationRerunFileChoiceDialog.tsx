import { VButton, VDialog } from "../vui";

const VISIBLE_PATHS = 8;

export type ConversationRerunFileChoiceDialogProps = {
  open: boolean;
  language: "zh" | "en";
  paths: readonly string[];
  pending: boolean;
  error: string;
  onOpenChange: (open: boolean) => void;
  onRestoreAndRerun: () => void;
  onRerunOnly: () => void;
};

/**
 * Three-way choice before a chat rerun replaces answers whose turns already
 * changed files. Restore stays a separate strict rewind; this dialog does not
 * force it.
 */
export function ConversationRerunFileChoiceDialog({
  open,
  language,
  paths,
  pending,
  error,
  onOpenChange,
  onRestoreAndRerun,
  onRerunOnly,
}: ConversationRerunFileChoiceDialogProps) {
  if (!open) return null;
  const zh = language === "zh";
  const visible = paths.slice(0, VISIBLE_PATHS);
  const hidden = Math.max(0, paths.length - visible.length);
  return (
    <VDialog
      data-vui="conversation-rerun-file-choice"
      open
      hideClose={pending}
      onOpenChange={(next) => {
        if (!next) onOpenChange(false);
      }}
      title={zh ? "重跑前要不要还原文件？" : "Restore files before rerunning?"}
      description={zh
        ? "从这里重跑会换掉后面的回答。这些文件是这段回答改过的，会留在磁盘上，除非你选择还原。"
        : "Rerunning from here replaces the later answers. These files were changed and stay on disk unless you restore them."}
      size="md"
      footer={(
        <>
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            isDisabled={pending}
            onPress={() => onOpenChange(false)}
          >
            {zh ? "取消" : "Cancel"}
          </VButton>
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            isDisabled={pending}
            onPress={onRerunOnly}
          >
            {zh ? "只重跑" : "Rerun only"}
          </VButton>
          <VButton
            type="button"
            variant="primary"
            density="compact"
            isDisabled={pending}
            onPress={onRestoreAndRerun}
          >
            {pending
              ? (zh ? "正在还原文件…" : "Restoring files…")
              : (zh ? "还原文件并重跑" : "Restore files and rerun")}
          </VButton>
        </>
      )}
    >
      {visible.length ? (
        <ul>
          {visible.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      ) : null}
      {hidden > 0 ? (
        <p>{zh ? `另外还有 ${hidden} 个` : `${hidden} more`}</p>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </VDialog>
  );
}
