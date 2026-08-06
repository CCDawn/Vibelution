import type { VStatusTone } from "../components/vui";

/** Visibility / injection state for memory list + detail chips. */
export function memoryVisibilityTone(active: boolean, injected: boolean): VStatusTone {
  if (injected) return "accent";
  if (active) return "success";
  return "neutral";
}

/** Project-memory proposal queue status. */
export function memoryProposalStatusTone(status: string): VStatusTone {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "pending") return "success";
  if (normalized === "conflict") return "accent";
  return "neutral";
}

/** Severity / priority labels (high|blocked|critical → danger, warning-like → warning). */
export function memoryPriorityTone(value: string): VStatusTone {
  const normalized = String(value || "").trim().toLowerCase();
  if (
    normalized.includes("high")
    || normalized.includes("critical")
    || normalized.includes("block")
    || normalized === "p0"
    || normalized === "error"
    || normalized === "danger"
  ) {
    return "danger";
  }
  if (
    normalized.includes("warn")
    || normalized.includes("med")
    || normalized === "p1"
    || normalized === "attention"
  ) {
    return "warning";
  }
  if (normalized.includes("ok") || normalized.includes("success") || normalized === "clear" || normalized === "active") {
    return "success";
  }
  return "neutral";
}
