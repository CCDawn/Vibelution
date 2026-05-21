import type { TranslationKey } from "./dictionary";

const PET_AVATAR_PRESET_LABEL_KEYS = {
  lobster: "petPresetLobster",
  shrimp: "petPresetShrimp",
  crab: "petPresetCrab",
  cat: "petPresetCat",
  chick: "petPresetChick",
  bunny: "petPresetBunny",
  slime: "petPresetSlime",
  penguin: "petPresetPenguin",
  moose: "petPresetMoose",
} as const satisfies Record<string, TranslationKey>;

export function petAvatarPresetLabel(
  t: (key: TranslationKey) => string,
  preset: string | null | undefined,
) {
  const presetId = String(preset || "").trim();
  if (!presetId) {
    return t("petPresetUnknown");
  }
  const labelKey = PET_AVATAR_PRESET_LABEL_KEYS[presetId as keyof typeof PET_AVATAR_PRESET_LABEL_KEYS];
  return labelKey ? t(labelKey) : presetId;
}
