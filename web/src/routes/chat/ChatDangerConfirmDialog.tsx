import { VConfirmDialog, type VConfirmDialogTone } from "../../components/vui";

type ChatDangerConfirmDialogProps = {
  cancelLabel: string;
  confirmLabel: string;
  confirmPending?: boolean;
  open: boolean;
  title: string;
  tone?: VConfirmDialogTone;
  onCancel: () => void;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
};

export function ChatDangerConfirmDialog({
  cancelLabel,
  confirmLabel,
  confirmPending = false,
  open,
  title,
  tone = "danger",
  onCancel,
  onConfirm,
  onOpenChange,
}: ChatDangerConfirmDialogProps) {
  return (
    <VConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      tone={tone}
      confirmLabel={confirmLabel}
      cancelLabel={cancelLabel}
      confirmPending={confirmPending}
      hideClose
      onCloseAutoFocus={(event) => {
        event.preventDefault();
      }}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}
