export type CompactPanelRow = {
  label: string;
  value: string;
  title?: string;
};

const PET_AVATAR_SYMBOLS: Record<string, string> = {
  lobster: "LOB",
  shrimp: "SHR",
  crab: "CRB",
  cat: "CAT",
  chick: "CHK",
  bunny: "BUN",
  slime: "SLM",
  penguin: "PNG",
  moose: "MOS",
};

const LOW_VALUE_VALUES = new Set(["", "--", "workspace"]);

export function getPetAvatarPresetKey(avatarPreset: string | null | undefined) {
  const normalized = String(avatarPreset ?? "").trim().toLowerCase();
  return normalized || "default";
}

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

export function getPetAvatarSymbol(avatarPreset: string | null | undefined, petName: string | null | undefined) {
  const presetSymbol = PET_AVATAR_SYMBOLS[getPetAvatarPresetKey(avatarPreset)];
  if (presetSymbol) {
    return presetSymbol;
  }

  return petName?.trim()?.slice(0, 2) || "PET";
}
