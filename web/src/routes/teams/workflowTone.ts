/**
 * Style-bound workflow tag tone helpers for Teams.
 * Accepts a style map so helpers stay free of route CSS imports.
 */
export type WorkflowToneStyles = {
  workflowTagReady: string;
  workflowTagDanger: string;
  workflowTagWarning: string;
  workflowTagNeutral: string;
};

export function workflowQualityTone(value: string, styles: WorkflowToneStyles) {
  const normalized = String(value || "").toLowerCase();
  if (normalized.includes("approved") || normalized.includes("ready") || normalized.includes("prefiltered")) {
    return styles.workflowTagReady;
  }
  if (normalized.includes("invalid") || normalized.includes("broken") || normalized.includes("rejected")) {
    return styles.workflowTagDanger;
  }
  if (normalized.includes("revision") || normalized.includes("pending")) {
    return styles.workflowTagWarning;
  }
  return styles.workflowTagNeutral;
}

export function workflowIngestionTone(value: string, styles: WorkflowToneStyles) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "ready" || normalized === "operational") {
    return styles.workflowTagReady;
  }
  if (normalized === "blocked" || normalized === "needs_revision") {
    return styles.workflowTagDanger;
  }
  if (
    normalized === "needs_review"
    || normalized === "needs_evidence"
    || normalized === "needs_screening"
    || normalized === "pending"
  ) {
    return styles.workflowTagWarning;
  }
  return styles.workflowTagNeutral;
}
