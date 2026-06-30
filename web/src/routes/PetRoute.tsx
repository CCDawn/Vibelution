import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { PetSummary } from "../api/types";
import { petAvatarPresetLabel } from "../i18n/petLabels";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./PetRoute.styles";

const ACHIEVEMENT_LABEL_KEYS = {
  first_task: "petAchievementFirstTask",
  level_10: "petAchievementLevel10",
} as const;


export function PetRoute() {
  const { t } = useAppI18n();
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchJson<PetSummary>("/api/pet/summary"),
  });

  const pet = petQuery.data;
  const progress = pet ? Math.round((pet.exp / pet.expToNext) * 100) : 0;
  const avatarPresetLabel = petAvatarPresetLabel(t, pet?.avatarPreset);

  return (
    <div className={styles.pageClass}>
      <section className={styles.heroClass}>
        <div className={styles.avatarPanelClass}>
          <div className={styles.avatarOrbClass}>{pet?.name?.[0] ?? "P"}</div>
          <p className={styles.avatarMetaClass}>
            {avatarPresetLabel} {t("preset")}
          </p>
        </div>
        <div className={styles.heroCopyClass}>
          <p className={styles.eyebrowClass}>{t("petSpace")}</p>
          <h1 className={styles.titleClass}>{pet?.name ?? t("loadingPetState")}</h1>
          <p className={styles.statusLineClass}>{pet?.statusLine ?? t("readingCompanionState")}</p>
        </div>
      </section>

      <section className={styles.metricGridClass}>
        <article className={styles.metricCardClass}>
          <span className={styles.metricLabelClass}>{t("level")}</span>
          <strong className={styles.metricValueClass}>{pet?.level ?? 0}</strong>
        </article>
        <article className={styles.metricCardClass}>
          <span className={styles.metricLabelClass}>{t("tasks")}</span>
          <strong className={styles.metricValueClass}>{pet?.totalTasks ?? 0}</strong>
        </article>
        <article className={styles.metricCardClass}>
          <span className={styles.metricLabelClass}>{t("friends")}</span>
          <strong className={styles.metricValueClass}>{pet?.friendCount ?? 0}</strong>
        </article>
        <article className={styles.metricCardClass}>
          <span className={styles.metricLabelClass}>{t("tokens")}</span>
          <strong className={styles.metricValueClass}>{pet?.totalTokens ?? 0}</strong>
        </article>
      </section>

      <section className={styles.statusGridClass}>
        <article className={styles.cardClass}>
          <p className={styles.cardTitleClass}>{t("vitals")}</p>
          <div className={styles.statListClass}>
            <span>{t("mood")} {pet?.mood ?? 0}</span>
            <span>{t("hunger")} {pet?.hunger ?? 0}</span>
            <span>{t("energy")} {pet?.energy ?? 0}</span>
            <span>{t("health")} {pet?.health ?? 0}</span>
            <span>{t("love")} {pet?.love ?? 0}</span>
          </div>
        </article>

        <article className={styles.cardClass}>
          <p className={styles.cardTitleClass}>{t("progress")}</p>
          <div className={styles.progressTrackClass}>
            <div className={styles.progressFillClass} style={{ width: `${progress}%` }} />
          </div>
          <p className={styles.supportTextClass}>
            {pet?.exp ?? 0} / {pet?.expToNext ?? 0} {t("exp")}
          </p>
        </article>

        <article className={styles.cardClass}>
          <p className={styles.cardTitleClass}>{t("state")}</p>
          <div className={styles.statListClass}>
            <span>{t("heart")} {pet?.heartActive ? t("heartActive") : t("heartIdle")}</span>
            <span>{t("dream")} {pet?.inDream ? t("dreamSleeping") : t("dreamAwake")}</span>
            <span>{t("dailyTokens")} {pet?.dailyTokens ?? 0}</span>
          </div>
        </article>
      </section>

      <section className={styles.cardClass}>
        <p className={styles.cardTitleClass}>{t("achievements")}</p>
        <div className={styles.badgeRowClass}>
          {(pet?.achievements ?? []).length > 0 ? (
            pet?.achievements.map((achievement) => (
              <span key={achievement} className={styles.badgeClass}>
                {ACHIEVEMENT_LABEL_KEYS[achievement as keyof typeof ACHIEVEMENT_LABEL_KEYS]
                  ? t(ACHIEVEMENT_LABEL_KEYS[achievement as keyof typeof ACHIEVEMENT_LABEL_KEYS])
                  : achievement}
              </span>
            ))
          ) : (
            <span className={styles.supportTextClass}>{t("noAchievements")}</span>
          )}
        </div>
      </section>
    </div>
  );
}
