type CleanupPreviewGate = {
  previewToken?: string;
  confirmationPhrase?: string;
};

type CleanupExecutionOutcome = {
  outcome?: string;
};

export function canExecuteMemoryCleanup(
  preview: CleanupPreviewGate | null,
  selectedTargetCount: number,
  confirmationText: string,
): boolean {
  return Boolean(
    preview?.previewToken?.trim()
      && selectedTargetCount > 0
      && confirmationText.trim() === preview.confirmationPhrase,
  );
}

export function isMemoryCleanupExecutionSuccessful(execution: CleanupExecutionOutcome): boolean {
  return execution.outcome === "succeeded";
}
