import type { LauncherRegistryReconciliationItem, LauncherStateSnapshotV1 } from "../api/launcher";

export const LAUNCHER_REGISTRY_DIAGNOSTIC_CHAR_LIMIT = 4000;
export const LAUNCHER_REGISTRY_DIAGNOSTIC_ITEM_LIMIT = 8;

function compactDate(value: string | undefined, locale: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return text.slice(0, 40);
  }
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function clip(value: string, limit: number) {
  const text = value.trim();
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 1))}…`;
}

export function isUnknownOrQuarantinedLease(item: LauncherRegistryReconciliationItem): boolean {
  const lease = String(item.portLeaseStatus || "").trim().toLowerCase();
  return item.classification === "unknown" || lease === "quarantined" || lease === "reclaimable";
}

export function formatUnknownLeaseDiagnostics(
  items: LauncherRegistryReconciliationItem[],
  uiLang: string,
  locale: string,
): string {
  const rows = items
    .filter(isUnknownOrQuarantinedLease)
    .map((item) => [
      item.instanceId,
      item.classification,
      item.portLeaseStatus,
      item.reasons.slice(0, 4).join("/"),
      item.firstObservedAt ? compactDate(item.firstObservedAt, locale) : "",
      item.nextReconcileAt ? compactDate(item.nextReconcileAt, locale) : "",
    ].filter(Boolean).join(" · "));
  if (rows.length === 0) {
    return uiLang === "zh" ? "无" : "None";
  }
  return rows.slice(0, 6).join("; ");
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
