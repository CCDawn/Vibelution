import type { RuntimeSummary } from "../api/types";
import type { Language, ShellTranslationKey } from "../i18n/shellDictionary";
import {
  backendSystemTone,
  frontendSystemTone,
  lifecycleStateLabel,
  lifecycleStateTone,
  runtimeControllerTone,
  type BackendSystemState,
  type FrontendSystemState,
  type RuntimeControllerState,
  type SystemStatusTone,
} from "./systemStatus";
import styles from "./AppShell.styles";

export type AppShellStatusSummaryCard = {
  id: "frontend" | "backend" | "runtime";
  label: string;
  value: string;
  tone: SystemStatusTone;
};

type StatusGuideCard = AppShellStatusSummaryCard & {
  note: string;
  states: Array<{ label: string; tone: SystemStatusTone; detail: string }>;
};

export type AppShellStatusGuidePanelProps = {
  lang: Language;
  t: (key: ShellTranslationKey) => string;
  cards: AppShellStatusSummaryCard[];
  frontendState: FrontendSystemState;
  backendState: BackendSystemState;
  runtimeControllerState: RuntimeControllerState;
  lifecycleProof?: RuntimeSummary["lifecycleProof"] | null;
  workbench?: RuntimeSummary["workbench"] | null;
  buildId: string;
};

export function AppShellStatusGuidePanel({
  lang,
  t,
  cards,
  frontendState,
  backendState,
  runtimeControllerState,
  lifecycleProof,
  workbench,
  buildId,
}: AppShellStatusGuidePanelProps) {
  const detailsById: Record<AppShellStatusSummaryCard["id"], Omit<StatusGuideCard, keyof AppShellStatusSummaryCard>> = {
    frontend: {
      note: `${t("systemFrontendHint")} · ${t("frontendBuild")} ${buildId}`,
      states: [
        {
          label: t("systemFrontend_connected"),
          tone: frontendSystemTone("connected"),
          detail: t("systemFrontendPossible_connected"),
        },
        {
          label: t("systemFrontend_background"),
          tone: frontendSystemTone("background"),
          detail: t("systemFrontendPossible_background"),
        },
        {
          label: t("systemFrontend_offline"),
          tone: frontendSystemTone("offline"),
          detail: t("systemFrontendPossible_offline"),
        },
      ],
    },
    backend: {
      note:
        backendState === "healthy"
          ? t("backendReachable")
          : backendState === "checking"
            ? t("backendNeverReached")
            : backendState === "offline"
              ? t("backendNoResponse")
              : t("systemBackendHint"),
      states: [
        {
          label: t("backendHealthy"),
          tone: backendSystemTone("healthy"),
          detail: t("systemBackendPossible_healthy"),
        },
        {
          label: t("backendChecking"),
          tone: backendSystemTone("checking"),
          detail: t("systemBackendPossible_checking"),
        },
        {
          label: t("backendOffline"),
          tone: backendSystemTone("offline"),
          detail: t("systemBackendPossible_offline"),
        },
        {
          label: t("backendUnhealthy"),
          tone: backendSystemTone("unhealthy"),
          detail: t("systemBackendPossible_unhealthy"),
        },
      ],
    },
    runtime: {
      note: lifecycleProof?.summary || workbench?.statusLine || t("systemRuntimeHint"),
      states: [
        {
          label: t("systemRuntime_managed"),
          tone: runtimeControllerTone("managed"),
          detail: t("systemRuntimePossible_managed"),
        },
        {
          label: t("systemRuntime_closing"),
          tone: runtimeControllerTone("closing"),
          detail: t("systemRuntimePossible_closing"),
        },
        {
          label: t("systemRuntime_unmanaged"),
          tone: runtimeControllerTone("unmanaged"),
          detail: t("systemRuntimePossible_unmanaged"),
        },
        {
          label: t("systemRuntime_failed"),
          tone: runtimeControllerTone("failed"),
          detail: t("systemRuntimePossible_failed"),
        },
      ],
    },
  };
  const detailCards: StatusGuideCard[] = cards.map((card) => ({
    ...card,
    ...detailsById[card.id],
  }));

  return (
    <div className={styles.statusGuidePanel} role="note" aria-live="polite">
      <div className={styles.statusGuideHeader} title={t("systemStatusGuideHint")}>
        <strong>{t("systemStatusGuide")}</strong>
      </div>
      <div className={styles.statusGuideGrid}>
        {detailCards.map((item) => (
          <section key={item.id} className={styles.statusGuideCard} title={item.note}>
            <div className={styles.statusGuideCardHeader}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
            <ul className={styles.statusGuideList}>
              {item.states.map((state) => (
                <li
                  key={`${item.id}-${state.label}`}
                  className={styles.statusGuideListItem}
                  data-current={state.label === item.value ? "true" : undefined}
                  title={state.detail}
                >
                  <span className={`${styles.statusDot} ${styles[`status_${state.tone}`]}`} />
                  <span className={styles.statusGuideStateLabel}>{state.label}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <section className={styles.lifecycleProofCard} title={lifecycleProof?.summary || t("lifecycleProofUnavailable")}>
        <div className={styles.lifecycleProofHeader}>
          <span>{t("lifecycleProofTitle")}</span>
          <strong>
            <span
              className={`${styles.statusDot} ${styles[`status_${lifecycleStateTone(lifecycleProof?.overallState)}`]}`}
            />
            {lifecycleProof?.overallLabel || t("lifecycleProofUnavailable")}
          </strong>
        </div>
        {lifecycleProof ? (
          <>
            <div className={styles.lifecycleProofMeta}>
              <span title={`${t("lifecycleProofDesiredObserved")}: ${lifecycleProof.desiredState} / ${lifecycleProof.observedState}`}>
                {t("lifecycleProofDesiredObserved")}
                <strong>
                  {lifecycleProof.desiredState} / {lifecycleProof.observedState}
                </strong>
              </span>
              <span title={`${t("lifecycleProofVerifiedAt")}: ${lifecycleProof.verifiedAt || "-"}`}>
                {t("lifecycleProofVerifiedAt")}
                <strong>{lifecycleProof.verifiedAt || "-"}</strong>
              </span>
            </div>
            <ul className={styles.lifecycleProofList}>
              {lifecycleProof.components.map((component) => (
                <li key={component.id} className={styles.lifecycleProofItem} title={component.detail}>
                  <span
                    className={`${styles.statusDot} ${styles[`status_${lifecycleStateTone(component.state)}`]}`}
                  />
                  <span className={styles.lifecycleProofName}>{component.label}</span>
                  <strong>{lifecycleStateLabel(component.state, lang)}</strong>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </section>
    </div>
  );
}
