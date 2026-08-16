import type { SessionSummary } from "../../api/types";
import { VConfirmDialog } from "../../components/vui";

type ChatSessionDeleteConfirmDialogProps = {
  cancelLabel: string;
  confirmLabel: string;
  confirmPending?: boolean;
  session: SessionSummary | null;
  title: string;
  onCancel: () => void;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
};

export function ChatSessionDeleteConfirmDialog({
  cancelLabel,
  confirmLabel,
  confirmPending = false,
  session,
  title,
  onCancel,
  onConfirm,
  onOpenChange,
}: ChatSessionDeleteConfirmDialogProps) {
  return (
    <VConfirmDialog
      open={Boolean(session)}
      onOpenChange={onOpenChange}
      title={title}
      tone="danger"
      confirmLabel={confirmLabel}
      cancelLabel={cancelLabel}
      confirmPending={confirmPending}
      hideClose
      onCloseAutoFocus={(event) => {
        // Keep focus off the tab/context-menu trigger; composer handoff owns restore.
        event.preventDefault();
      }}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}
