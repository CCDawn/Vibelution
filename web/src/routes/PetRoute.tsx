import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { PetSummary } from "../api/types";
import { petAvatarPresetLabel } from "../i18n/petLabels";
import { useAppI18n } from "../i18n/useAppI18n";

const ACHIEVEMENT_LABEL_KEYS = {
  first_task: "petAchievementFirstTask",
  level_10: "petAchievementLevel10",
} as const;

const pageClass = "grid h-full min-h-0 content-start gap-1.5 overflow-auto p-[var(--route-workspace-padding)]";
const surfaceClass = "rounded-lg border border-vui-border-soft bg-[var(--surface-panel)]";
const heroClass = `${surfaceClass} grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2.5 p-[var(--route-topbar-padding)] max-[640px]:grid-cols-1`;
const avatarPanelClass = "inline-flex min-w-0 items-center gap-[7px] rounded-lg bg-[var(--surface-panel-strong)] px-2 py-1.5";
const avatarOrbClass = "grid h-[34px] w-[34px] place-items-center rounded-lg bg-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] font-[var(--font-body)] text-base font-bold text-[var(--accent-warm-2)]";
const avatarMetaClass = "m-0 max-w-[110px] truncate text-[0.78rem] text-vui-fg-secondary";
const heroCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-[3px] text-[0.72rem] uppercase tracking-[0.08em] text-vui-fg-tertiary";
const titleClass = "m-0 text-[var(--route-topbar-title-size)] font-bold leading-[1.1] text-vui-fg-primary";
const statusLineClass = "m-0 mt-0.5 truncate text-[var(--route-topbar-subtitle-size)] text-vui-fg-secondary max-[640px]:whitespace-normal";
const metricGridClass = "grid grid-cols-4 gap-1.5 max-[860px]:grid-cols-2 max-[640px]:grid-cols-1";
const metricCardClass = `${surfaceClass} grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-2 p-[9px]`;
const metricLabelClass = "whitespace-nowrap text-[0.74rem] text-vui-fg-secondary";
const metricValueClass = "min-w-0 truncate text-[0.9rem] text-vui-fg-primary";
const statusGridClass = "grid grid-cols-3 items-start gap-1.5 max-[860px]:grid-cols-2 max-[640px]:grid-cols-1";
const cardClass = `${surfaceClass} p-[9px]`;
const cardTitleClass = eyebrowClass;
const statListClass = "grid gap-1 text-[0.8rem] text-vui-fg-secondary";
const progressTrackClass = "h-1.5 overflow-hidden rounded-[var(--radius-control)] bg-[var(--surface-panel-strong)]";
const progressFillClass = "h-full bg-[var(--vui-gradient-route-soft)]";
const supportTextClass = "text-vui-fg-secondary";
const badgeRowClass = "flex flex-wrap gap-1.5";
const badgeClass = "rounded-[var(--radius-control)] bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] px-[7px] py-1 text-[0.76rem] text-[var(--accent-cool)]";

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
    <div className={pageClass}>
      <section className={heroClass}>
        <div className={avatarPanelClass}>
          <div className={avatarOrbClass}>{pet?.name?.[0] ?? "P"}</div>
          <p className={avatarMetaClass}>
            {avatarPresetLabel} {t("preset")}
          </p>
        </div>
        <div className={heroCopyClass}>
          <p className={eyebrowClass}>{t("petSpace")}</p>
          <h1 className={titleClass}>{pet?.name ?? t("loadingPetState")}</h1>
          <p className={statusLineClass}>{pet?.statusLine ?? t("readingCompanionState")}</p>
        </div>
      </section>

      <section className={metricGridClass}>
        <article className={metricCardClass}>
          <span className={metricLabelClass}>{t("level")}</span>
          <strong className={metricValueClass}>{pet?.level ?? 0}</strong>
        </article>
        <article className={metricCardClass}>
          <span className={metricLabelClass}>{t("tasks")}</span>
          <strong className={metricValueClass}>{pet?.totalTasks ?? 0}</strong>
        </article>
        <article className={metricCardClass}>
          <span className={metricLabelClass}>{t("friends")}</span>
          <strong className={metricValueClass}>{pet?.friendCount ?? 0}</strong>
        </article>
        <article className={metricCardClass}>
          <span className={metricLabelClass}>{t("tokens")}</span>
          <strong className={metricValueClass}>{pet?.totalTokens ?? 0}</strong>
        </article>
      </section>

      <section className={statusGridClass}>
        <article className={cardClass}>
          <p className={cardTitleClass}>{t("vitals")}</p>
          <div className={statListClass}>
            <span>{t("mood")} {pet?.mood ?? 0}</span>
            <span>{t("hunger")} {pet?.hunger ?? 0}</span>
            <span>{t("energy")} {pet?.energy ?? 0}</span>
            <span>{t("health")} {pet?.health ?? 0}</span>
            <span>{t("love")} {pet?.love ?? 0}</span>
          </div>
        </article>

        <article className={cardClass}>
          <p className={cardTitleClass}>{t("progress")}</p>
          <div className={progressTrackClass}>
            <div className={progressFillClass} style={{ width: `${progress}%` }} />
          </div>
          <p className={supportTextClass}>
            {pet?.exp ?? 0} / {pet?.expToNext ?? 0} {t("exp")}
          </p>
        </article>

        <article className={cardClass}>
          <p className={cardTitleClass}>{t("state")}</p>
          <div className={statListClass}>
            <span>{t("heart")} {pet?.heartActive ? t("heartActive") : t("heartIdle")}</span>
            <span>{t("dream")} {pet?.inDream ? t("dreamSleeping") : t("dreamAwake")}</span>
            <span>{t("dailyTokens")} {pet?.dailyTokens ?? 0}</span>
          </div>
        </article>
      </section>

      <section className={cardClass}>
        <p className={cardTitleClass}>{t("achievements")}</p>
        <div className={badgeRowClass}>
          {(pet?.achievements ?? []).length > 0 ? (
            pet?.achievements.map((achievement) => (
              <span key={achievement} className={badgeClass}>
                {ACHIEVEMENT_LABEL_KEYS[achievement as keyof typeof ACHIEVEMENT_LABEL_KEYS]
                  ? t(ACHIEVEMENT_LABEL_KEYS[achievement as keyof typeof ACHIEVEMENT_LABEL_KEYS])
                  : achievement}
              </span>
            ))
          ) : (
            <span className={supportTextClass}>{t("noAchievements")}</span>
          )}
        </div>
      </section>
    </div>
  );
}
