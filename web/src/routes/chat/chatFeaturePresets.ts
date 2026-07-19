import type { TranslationKey } from "../../i18n/dictionary";

export type FeaturePresetKey = "planningMode" | "goalMode" | "toolBoost";

export const CHAT_FEATURE_PRESETS: Array<{
  key: FeaturePresetKey;
  labelKey: TranslationKey;
  hintKey: TranslationKey;
}> = [
  {
    key: "planningMode",
    labelKey: "chatFeaturePlanningMode",
    hintKey: "chatFeaturePlanningModeHint",
  },
  {
    key: "goalMode",
    labelKey: "chatFeatureGoalMode",
    hintKey: "chatFeatureGoalModeHint",
  },
  {
    key: "toolBoost",
    labelKey: "chatFeatureToolBoost",
    hintKey: "chatFeatureToolBoostHint",
  },
];

export const DEFAULT_CHAT_FEATURE_PRESETS: Record<FeaturePresetKey, boolean> = {
  planningMode: false,
  goalMode: false,
  toolBoost: false,
};

export function chatFeaturePresetShortLabel(key: FeaturePresetKey, lang: string, fallback: string): string {
  if (lang !== "zh") {
    return fallback;
  }
  switch (key) {
    case "planningMode":
      return "计划";
    case "goalMode":
      return "目标";
    case "toolBoost":
      return "工具";
    default:
      return fallback;
  }
}
