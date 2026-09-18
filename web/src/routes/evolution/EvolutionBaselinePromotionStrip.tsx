import { VMetricStrip } from "../../components/vui";
import type { EvolutionBaselinePromotion } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import {
  promotionStatusLabel,
  promotionStatusTone,
  shortPromotionCommit,
} from "./evolutionBaselinePromotion";

type EvolutionBaselinePromotionStripProps = {
  lang: "zh" | "en";
  promotion: EvolutionBaselinePromotion | null | undefined;
  t: (key: TranslationKey) => string;
};

export function EvolutionBaselinePromotionStrip({
  lang,
  promotion,
  t,
}: EvolutionBaselinePromotionStripProps) {
  const status = promotion?.status || "none";
  return (
    <VMetricStrip
      ariaLabel={lang === "zh" ? "当前 Git 晋级基线" : "Current Git promotion baseline"}
      status={{
        label: promotionStatusLabel(promotion, lang, t),
        tone: promotionStatusTone(status),
        title: promotion?.commitSha || undefined,
      }}
      metrics={[
        {
          id: "lane",
          label: t("promotionLane"),
          value: "expected_head",
          detail: lang === "zh"
            ? "批准后只能经 expected_head 合入 local main"
            : "Approved candidates may land on local main only through expected_head",
        },
        {
          id: "commit",
          label: t("promotionCommit"),
          value: shortPromotionCommit(promotion?.commitSha),
          detail: promotion?.commitSha || undefined,
          tone: promotionStatusTone(status),
        },
        {
          id: "files",
          label: lang === "zh" ? "变更文件" : "Files",
          value: promotion?.changedFiles?.length ?? 0,
        },
      ]}
    />
  );
}
