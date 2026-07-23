import { useState } from "react";
import { Archive, CheckCircle2, CheckSquare, Square, Trash2 } from "lucide-react";

import { AgentBulkActionBar } from "../components/vui/product/agent-management";
import { VButton, VConfirmDialog, VHStack, VNativeSelect } from "../components/vui";
import styles from "./AgentBulkOperationsPanel.styles";

export type AgentBulkPromptTemplateOption = {
  value: string;
  label: string;
};

type AgentBulkOperationsCopy = {
  bulkSelected: string;
  bulkClear: string;
  bulkSelectVisible: string;
  bulkPromptLabel: string;
  bulkPromptPlaceholder: string;
  bulkApplyPrompt: string;
  bulkArchive: string;
  bulkPurge: string;
  bulkWorking: string;
  bulkArchiveConfirm: string;
  bulkPurgeConfirm: string;
  cancelCreate: string;
};

type ConfirmKind = "archive" | "purge" | null;

type AgentBulkOperationsPanelProps = {
  copy: AgentBulkOperationsCopy;
  selectedCount: number;
  visibleCount: number;
  allVisibleSelected: boolean;
  pending: boolean;
  selectedPromptTemplateId: string;
  promptTemplateOptions: AgentBulkPromptTemplateOption[];
  onSelectVisible: () => void;
  onClearSelection: () => void;
  onPromptTemplateChange: (templateId: string) => void;
  onApplyPromptTemplate: () => void;
  onArchive: () => void;
  onPurge: () => void;
};

export function AgentBulkOperationsPanel({
  copy,
  selectedCount,
  visibleCount,
  allVisibleSelected,
  pending,
  selectedPromptTemplateId,
  promptTemplateOptions,
  onSelectVisible,
  onClearSelection,
  onPromptTemplateChange,
  onApplyPromptTemplate,
  onArchive,
  onPurge,
}: AgentBulkOperationsPanelProps) {
  const [confirmKind, setConfirmKind] = useState<ConfirmKind>(null);
  const hasSelection = selectedCount > 0;
  const hasVisibleAgents = visibleCount > 0;
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
        isDisabled={!hasVisibleAgents || pending}
        onPress={allVisibleSelected ? onClearSelection : onSelectVisible}
      >
        {allVisibleSelected ? copy.bulkClear : copy.bulkSelectVisible}
      </VButton>
      <VButton
        type="button"
        variant="secondary"
        icon={<Square size={14} />}
        isDisabled={!hasSelection || pending}
        onPress={onClearSelection}
      >
        {copy.bulkClear}
      </VButton>
    </>
  );
  const promptPicker = (
    <VHStack className={styles.bulkPromptPicker}>
      <label className={styles.bulkPromptLabel} htmlFor="agents-bulk-prompt">
        {copy.bulkPromptLabel}
      </label>
      <VNativeSelect
        id="agents-bulk-prompt"
        value={selectedPromptTemplateId}
        disabled={pending}
        onChange={(event) => onPromptTemplateChange(event.target.value)}
      >
        <option value="">{copy.bulkPromptPlaceholder}</option>
        {promptTemplateOptions.map((template) => (
          <option key={template.value} value={template.value}>
            {template.label}
          </option>
        ))}
      </VNativeSelect>
    </VHStack>
  );
  const mutationActions = (
    <>
      <VButton
        type="button"
        variant="primary"
        icon={<CheckCircle2 size={14} />}
        isDisabled={!hasSelection || !selectedPromptTemplateId || pending}
        onPress={onApplyPromptTemplate}
      >
        {workingLabel ?? copy.bulkApplyPrompt}
      </VButton>
      <VButton
        type="button"
        variant="secondary"
        icon={<Archive size={14} />}
        isDisabled={!hasSelection || pending}
        onPress={() => setConfirmKind("archive")}
      >
        {workingLabel ?? copy.bulkArchive}
      </VButton>
    </>
  );
  const destructiveActions = (
    <VButton
      type="button"
      variant="danger"
      icon={<Trash2 size={14} />}
      isDisabled={!hasSelection || pending}
      onPress={() => setConfirmKind("purge")}
    >
      {workingLabel ?? copy.bulkPurge}
    </VButton>
  );

  const confirmOpen = confirmKind !== null;
  const confirmDialog = (
    <VConfirmDialog
      open={confirmOpen}
      onOpenChange={(open) => {
        if (!open) {
          setConfirmKind(null);
        }
      }}
      title={confirmKind === "purge" ? copy.bulkPurge : copy.bulkArchive}
      description={confirmKind === "purge" ? copy.bulkPurgeConfirm : copy.bulkArchiveConfirm}
      tone={confirmKind === "purge" ? "danger" : "neutral"}
      confirmLabel={confirmKind === "purge" ? copy.bulkPurge : copy.bulkArchive}
      cancelLabel={copy.cancelCreate}
      confirmPending={pending}
      onConfirm={() => {
        if (confirmKind === "purge") {
          onPurge();
        } else if (confirmKind === "archive") {
          onArchive();
        }
        setConfirmKind(null);
      }}
    />
  );

  // Compact by default: only selection controls until the user picks agents.
  if (!hasSelection) {
    return (
      <>
        <AgentBulkActionBar
          ariaLabel={copy.bulkSelected}
          summary={summary}
          selectionActions={
            <VButton
              type="button"
              variant="secondary"
              icon={allVisibleSelected ? <Square size={14} /> : <CheckSquare size={14} />}
              isDisabled={!hasVisibleAgents || pending}
              onPress={allVisibleSelected ? onClearSelection : onSelectVisible}
            >
              {allVisibleSelected ? copy.bulkClear : copy.bulkSelectVisible}
            </VButton>
          }
        />
        {confirmDialog}
      </>
    );
  }

  return (
    <>
      <AgentBulkActionBar
        ariaLabel={copy.bulkSelected}
        summary={summary}
        selectionActions={selectionActions}
        promptPicker={promptPicker}
        mutationActions={mutationActions}
        destructiveActions={destructiveActions}
      />
      {confirmDialog}
    </>
  );
}
