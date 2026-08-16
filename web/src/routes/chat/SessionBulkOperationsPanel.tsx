import { useState } from "react";
import { CheckSquare, Square, Trash2 } from "lucide-react";

import { AgentBulkActionBar } from "../../components/vui/product/agent-management";
import { VButton, VConfirmDialog } from "../../components/vui";
import styles from "./SessionBulkOperationsPanel.styles";

type SessionBulkOperationsCopy = {
  bulkSelected: string;
  bulkClear: string;
  bulkSelectVisible: string;
  bulkRemove: string;
  bulkWorking: string;
  bulkRemoveConfirm: string;
  cancelCreate: string;
};

type SessionBulkOperationsPanelProps = {
  copy: SessionBulkOperationsCopy;
  selectedCount: number;
  visibleCount: number;
  allVisibleSelected: boolean;
  pending: boolean;
  onSelectVisible: () => void;
  onClearSelection: () => void;
  onRemove: () => void;
};

export function SessionBulkOperationsPanel({
  copy,
  selectedCount,
  visibleCount,
  allVisibleSelected,
  pending,
  onSelectVisible,
  onClearSelection,
  onRemove,
}: SessionBulkOperationsPanelProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const hasSelection = selectedCount > 0;
  const hasVisibleSessions = visibleCount > 0;
  const workingLabel = pending ? copy.bulkWorking : undefined;
  const summary = (
    <>
      <CheckSquare size={15} />
      <strong>{copy.bulkSelected}</strong>
      <span>{selectedCount} / {visibleCount}</span>
    </>
  );
  const selectionActions = (
    <>
      <VButton
        type="button"
        variant="secondary"
        icon={allVisibleSelected ? <Square size={14} /> : <CheckSquare size={14} />}
        isDisabled={!hasVisibleSessions || pending}
        onPress={allVisibleSelected ? onClearSelection : onSelectVisible}
      >
        {allVisibleSelected ? copy.bulkClear : copy.bulkSelectVisible}
      </VButton>
      {hasSelection ? (
        <VButton
          type="button"
          variant="secondary"
          isDisabled={pending}
          onPress={onClearSelection}
        >
          {copy.bulkClear}
        </VButton>
      ) : null}
    </>
  );
  const destructiveActions = (
    <VButton
      type="button"
      variant="danger"
      icon={<Trash2 size={14} />}
      isDisabled={!hasSelection || pending}
      onPress={() => setConfirmOpen(true)}
    >
      {workingLabel ?? copy.bulkRemove}
    </VButton>
  );

  if (!hasSelection) {
    return null;
  }

  return (
    <>
      <AgentBulkActionBar
        ariaLabel={copy.bulkSelected}
        className={styles.sessionBulkBar}
        summary={summary}
        selectionActions={selectionActions}
        destructiveActions={destructiveActions}
      />
      <VConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={copy.bulkRemove}
        description={copy.bulkRemoveConfirm}
        tone="danger"
        confirmLabel={copy.bulkRemove}
        cancelLabel={copy.cancelCreate}
        confirmPending={pending}
        onConfirm={() => {
          onRemove();
          setConfirmOpen(false);
        }}
      />
    </>
  );
}
