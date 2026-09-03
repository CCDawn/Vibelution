/**
 * Two-stage zone divider for the single-question acceptance page.
 *
 * Splits the anchor sections into the descriptive zones 假说生成 / 研究计划与
 * 实验 and carries the question-level stage state: zone one shows the derived
 * stage-one status (假说生成中 / 假说已定), zone two always shows 未激活 —
 * stage two never auto-activates. Display only; no activation action exists.
 */
import { VStatusChip, type VStatusTone } from "../../../components/vui";
import {
  stageOneStatusCopy,
  stageTwoInactiveHint,
  stageTwoStatusCopy,
  stageZoneTitle,
  type ChallengeQuestionStageOneStatus,
} from "./challengeQuestionStageModel";
import css from "./ChallengeQuestionDetailPanel.styles";

export function ChallengeQuestionStageZoneHeading({
  zone,
  stageOneStatus,
  lang = "zh",
}: {
  zone: "hypothesis" | "plan";
  /** Only read for zone="hypothesis"; zone two is permanently inactive. */
  stageOneStatus?: ChallengeQuestionStageOneStatus;
  lang?: "zh" | "en";
}) {
  const isZh = lang === "zh";
  const chipTone: VStatusTone = zone === "plan"
    ? "neutral"
    : stageOneStatus === "hypothesis_settled"
      ? "success"
      : "accent";
  const chipLabel = zone === "plan"
    ? stageTwoStatusCopy(isZh ? "zh" : "en")
    : stageOneStatusCopy(stageOneStatus ?? "hypothesis_generating", isZh ? "zh" : "en");
  return (
    <section
      className={css.stageZone}
      data-stage-zone={zone}
      data-testid={`question-stage-zone-${zone}`}
      aria-label={stageZoneTitle(zone, isZh ? "zh" : "en")}
    >
      <div className={css.stageZoneTopline}>
        <h3 className={css.stageZoneTitle}>{stageZoneTitle(zone, isZh ? "zh" : "en")}</h3>
        <VStatusChip tone={chipTone}>{chipLabel}</VStatusChip>
      </div>
      {zone === "plan" ? (
        <p className={css.stageZoneHint}>{stageTwoInactiveHint(isZh ? "zh" : "en")}</p>
      ) : null}
    </section>
  );
}
