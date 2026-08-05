import { useEffect, useId, useRef } from "react";

import { VButton, VDialog, VNativeInput } from "../components/vui";
import type { AgentRenameDraft } from "./chat/useChatAgentDirectoryActions";

type AgentRenameDialogProps = {
  draft: AgentRenameDraft;
  lang: "zh" | "en";
  pending?: boolean;
  onCancel: () => void;
  onChange: (draftName: string) => void;
  onSubmit: () => void;
};

/**
 * In-app Agent rename surface. Native browser prompts are blocked in Electron shells.
 */
export function AgentRenameDialog({
  draft,
  lang,
  pending = false,
  onCancel,
  onChange,
  onSubmit,
}: AgentRenameDialogProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const title = lang === "zh" ? "重命名 Agent" : "Rename Agent";
  const description = lang === "zh"
    ? "修改显示名称；不会改动 agentId 或历史会话。"
    : "Change the display name. agentId and history stay the same.";
  const confirmLabel = lang === "zh" ? "保存" : "Save";
  const cancelLabel = lang === "zh" ? "取消" : "Cancel";
  const canSubmit = Boolean(draft.draftName.trim()) && !pending;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [draft.agentId]);

  return (
    <VDialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) {
          onCancel();
        }
      }}
      title={title}
      description={description}
      size="sm"
      aria-label={title}
      footer={(
        <>
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            isDisabled={pending}
            onPress={onCancel}
          >
            {cancelLabel}
          </VButton>
          <VButton
            type="button"
            variant="primary"
            density="compact"
            isDisabled={!canSubmit}
            isPending={pending}
            onPress={onSubmit}
          >
            {confirmLabel}
          </VButton>
        </>
      )}
    >
      <label htmlFor={inputId} className="sr-only">
        {lang === "zh" ? "Agent 名称" : "Agent name"}
      </label>
      <VNativeInput
        id={inputId}
        ref={inputRef}
        value={draft.draftName}
        maxLength={80}
        autoComplete="off"
        spellCheck={false}
        disabled={pending}
        placeholder={draft.currentName}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            if (canSubmit) {
              onSubmit();
            }
          }
          if (event.key === "Escape") {
            event.preventDefault();
            if (!pending) {
              onCancel();
            }
          }
        }}
      />
    </VDialog>
  );
}
