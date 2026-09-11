export type CompactPanelRow = {
  label: string;
  value: string;
  title?: string;
};

export type ChatResponsiveLayoutMode = "wide" | "compact" | "overlay" | "mobile";

export type ChatResponsiveLayout = {
  mode: ChatResponsiveLayoutMode;
  leftVisible: boolean;
  rightVisible: boolean;
};

export function resolveChatResponsiveLayout(width: number): ChatResponsiveLayout {
  if (width < 640) return { mode: "mobile", leftVisible: false, rightVisible: false };
  if (width < 960) return { mode: "overlay", leftVisible: false, rightVisible: false };
  if (width < 1280) return { mode: "compact", leftVisible: true, rightVisible: false };
  return { mode: "wide", leftVisible: true, rightVisible: true };
}

export function resolveChatUserDisplayName(candidate: string | null | undefined) {
  const normalized = String(candidate ?? "").trim();
  return !normalized || /^\d+$/.test(normalized) ? "操作者" : normalized;
}

const LOW_VALUE_VALUES = new Set(["", "--", "workspace"]);

export function compactValue(value: string | null | undefined) {
  return String(value ?? "").trim();
}

export function isLowValuePanelText(value: string | null | undefined, lowValueLabels: string[] = []) {
  const normalized = compactValue(value).toLowerCase();
  if (LOW_VALUE_VALUES.has(normalized)) {
    return true;
  }
  return lowValueLabels.some((label) => normalized === compactValue(label).toLowerCase());
}

export function buildVisiblePanelRows(
  rows: Array<{ label: string; value: string | null | undefined; title?: string }>,
  lowValueLabels: string[] = [],
): CompactPanelRow[] {
  return rows
    .map((row) => ({
      label: row.label,
      value: compactValue(row.value),
      title: row.title,
    }))
    .filter((row) => row.label.trim() && !isLowValuePanelText(row.value, lowValueLabels));
}
