import type { EvolutionBaselinePromotion } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";

export function shortPromotionCommit(value: string | undefined): string {
  const commit = String(value || "").trim();
  if (!commit) {
    return "--";
  }
  return commit.slice(0, 12);
}

export function promotionStatusTone(
  status: EvolutionBaselinePromotion["status"] | undefined,
): "neutral" | "success" | "warning" {
  if (status === "current") {
    return "success";
  }
  if (status === "superseded") {
    return "warning";
  }
  return "neutral";
}

export function promotionStatusLabel(
  promotion: EvolutionBaselinePromotion | null | undefined,
  lang: "zh" | "en",
  t: (key: TranslationKey) => string,
): string {
  const status = promotion?.status || "none";
  if (status === "current") {
    return t("promotionCurrent");
  }
  if (status === "superseded") {
    return t("promotionSuperseded");
  }
  return t("promotionNone");
}
