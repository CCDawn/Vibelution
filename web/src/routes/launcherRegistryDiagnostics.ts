import type { LauncherRegistryReconciliationItem, LauncherStateSnapshotV1 } from "../api/launcher";

export const LAUNCHER_REGISTRY_DIAGNOSTIC_CHAR_LIMIT = 4000;
export const LAUNCHER_REGISTRY_DIAGNOSTIC_ITEM_LIMIT = 8;

const RESIDUE_CLASSIFICATIONS = ["conflict", "orphan", "stale", "unknown"] as const;

function clip(value: string, limit: number) {
  const text = value.trim();
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function classificationLabel(classification: (typeof RESIDUE_CLASSIFICATIONS)[number], uiLang: string): string {
  if (uiLang !== "zh") {
    return classification;
  }
  switch (classification) {
    case "conflict":
      return "冲突";
    case "orphan":
      return "孤儿";
    case "stale":
      return "过期";
    case "unknown":
      return "未知";
  }
}

export type LauncherRegistryNoticeFact = {
  key: string;
  label: string;
  value: string;
};

export function isUnknownOrQuarantinedLease(item: LauncherRegistryReconciliationItem): boolean {
  const lease = String(item.portLeaseStatus || "").trim().toLowerCase();
  return item.classification === "unknown" || lease === "quarantined" || lease === "reclaimable";
}

export function formatUnknownLeaseDiagnostics(
  items: LauncherRegistryReconciliationItem[],
  uiLang: string,
  _locale?: string,
): string {
  const rows = items.filter(isUnknownOrQuarantinedLease);
  if (rows.length === 0) {
    return uiLang === "zh" ? "无" : "None";
  }
  const reclaimable = rows.filter((item) => String(item.portLeaseStatus || "").toLowerCase() === "reclaimable").length;
  const quarantined = rows.filter((item) => String(item.portLeaseStatus || "").toLowerCase() === "quarantined").length;
  const parts = [String(rows.length)];
  if (reclaimable > 0 && reclaimable !== rows.length) {
    parts.push(uiLang === "zh" ? `可回收 ${reclaimable}` : `reclaimable ${reclaimable}`);
  } else if (reclaimable === rows.length) {
    parts.push(uiLang === "zh" ? "可回收" : "reclaimable");
  }
  if (quarantined > 0) {
    parts.push(uiLang === "zh" ? `隔离 ${quarantined}` : `quarantined ${quarantined}`);
  }
  return parts.join(" · ");
}

export function buildLauncherRegistryNoticeFacts(input: {
  uiLang: string;
  cleanup: LauncherStateSnapshotV1["cleanup"];
}): LauncherRegistryNoticeFact[] {
  const facts: LauncherRegistryNoticeFact[] = [];
  const items = input.cleanup.classifications;
  const residue = RESIDUE_CLASSIFICATIONS
    .map((classification) => {
      const count = items.filter((item) => item.classification === classification).length;
      return count > 0 ? `${classificationLabel(classification, input.uiLang)} ${count}` : "";
    })
    .filter(Boolean);
  if (residue.length) {
    facts.push({
      key: "residue",
      label: input.uiLang === "zh" ? "残留" : "Residue",
      value: residue.join(" · "),
    });
  }

  if (input.cleanup.portConflicts.length) {
    facts.push({
      key: "ports",
      label: input.uiLang === "zh" ? "端口冲突" : "Port conflicts",
      value: input.cleanup.portConflicts
        .map((item) => `${item.instanceId}${item.ports.length ? `:${item.ports.join("/")}` : ""}`)
        .join(", "),
    });
  }

  if (input.cleanup.cleanedCount > 0) {
    facts.push({
      key: "cleaned",
      label: input.uiLang === "zh" ? "已清理" : "Cleaned",
      value: String(input.cleanup.cleanedCount),
    });
  }

  if (input.cleanup.removedInstanceIds.length) {
    facts.push({
      key: "removed",
      label: input.uiLang === "zh" ? "已移除" : "Removed",
      value: String(input.cleanup.removedInstanceIds.length),
    });
  }

  if (input.cleanup.worktreeDryRun.length) {
    facts.push({
      key: "dry-run",
      label: "dry-run",
      value: String(input.cleanup.worktreeDryRun.length),
    });
  }

  return facts;
}

export function buildLauncherRegistryDiagnosticText(input: {
  snapshot?: Pick<LauncherStateSnapshotV1, "revision" | "observedAt" | "freshness" | "staleReason" | "nextReconcileAt"> | null;
  items: LauncherRegistryReconciliationItem[];
  uiLang: string;
}): string {
  const lines: string[] = [];
  const snapshot = input.snapshot;
  if (snapshot) {
    lines.push(`revision=${snapshot.revision}`);
    lines.push(`observedAt=${snapshot.observedAt}`);
    lines.push(`freshness=${snapshot.freshness}`);
    if (snapshot.staleReason) {
      lines.push(`staleReason=${clip(snapshot.staleReason, 200)}`);
    }
    if (snapshot.nextReconcileAt) {
      lines.push(`nextReconcileAt=${snapshot.nextReconcileAt}`);
    }
  }
  const residue = formatUnknownLeaseDiagnostics(input.items, input.uiLang);
  if (residue !== "无" && residue !== "None") {
    lines.push(`unknownOrLease=${residue}`);
  }
  const items = input.items.slice(0, LAUNCHER_REGISTRY_DIAGNOSTIC_ITEM_LIMIT);
  if (items.length === 0) {
    lines.push(input.uiLang === "zh" ? "registry=无" : "registry=none");
  } else {
    for (const item of items) {
      lines.push([
        clip(item.instanceId, 80),
        `class=${item.classification}`,
        item.portLeaseStatus ? `lease=${clip(item.portLeaseStatus, 40)}` : "",
        item.reasons.length ? `reasons=${clip(item.reasons.slice(0, 4).join("/"), 240)}` : "",
        item.windowOpen ? "window=open" : "window=closed",
        item.listener.length ? `listener=${clip(item.listener.slice(0, 4).join("/"), 80)}` : "",
        item.ports.length ? `ports=${item.ports.slice(0, 4).join("/")}` : "",
        item.firstObservedAt ? `firstObservedAt=${item.firstObservedAt}` : "",
        item.nextReconcileAt ? `nextReconcileAt=${item.nextReconcileAt}` : "",
      ].filter(Boolean).join(" | "));
    }
  }
  const text = lines.join("\n");
  if (text.length <= LAUNCHER_REGISTRY_DIAGNOSTIC_CHAR_LIMIT) {
    return text;
  }
  return `${text.slice(0, LAUNCHER_REGISTRY_DIAGNOSTIC_CHAR_LIMIT - 1)}…`;
}

export async function copyLauncherRegistryDiagnostics(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
}
