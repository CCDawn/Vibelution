import { VConfirmDialog, VSelect } from "../vui";

/** Copy scope for forking a new session from one journal node. */
export type ConversationForkScope = "visible_path" | "with_branches";

export type ConversationForkSessionDialogProps = {
  open: boolean;
  scope: ConversationForkScope;
  pending: boolean;
  labels: {
    title: string;
    description: string;
    scopeLabel: string;
    scopeVisiblePath: string;
    scopeWithBranches: string;
    confirm: string;
    pending: string;
    cancel: string;
  };
  onScopeChange: (scope: ConversationForkScope) => void;
  onConfirm: () => void;
  onCancel: () => void;
};

/**
 * Branch feature fork exit (designs/product/conversation.md):
 * confirms copying the active path up to one journal node into a new session.
 * Composes VConfirmDialog + VSelect; the route owns the API call and
 * navigation, the source session is never modified.
 */
export function ConversationForkSessionDialog({
  open,
  scope,
  pending,
  labels,
  onScopeChange,
  onConfirm,
  onCancel,
}: ConversationForkSessionDialogProps) {
  if (!open) {
    return null;
  }
  return (
    <VConfirmDialog
      open
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !pending) {
          onCancel();
        }
      }}
      title={labels.title}
      description={labels.description}
      confirmLabel={pending ? labels.pending : labels.confirm}
      cancelLabel={labels.cancel}
      confirmPending={pending}
      onConfirm={onConfirm}
      onCancel={() => {
        if (!pending) {
          onCancel();
        }
      }}
    >
      <div className="mt-1 flex w-full flex-col gap-2 [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]">
        <span>{labels.scopeLabel}</span>
        <VSelect
          aria-label={labels.scopeLabel}
          selectedKey={scope}
          options={[
            { id: "visible_path", label: labels.scopeVisiblePath },
            { id: "with_branches", label: labels.scopeWithBranches },
          ]}
          onSelectionChange={(key) => onScopeChange(
            String(key) === "with_branches" ? "with_branches" : "visible_path",
          )}
        />
      </div>
    </VConfirmDialog>
  );
}
