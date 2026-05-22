export type CompactPanelRow = {
  label: string;
  value: string;
  title?: string;
};

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
