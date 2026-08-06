import type { RuntimeSummary } from "../api/types";
import type { Language, ShellTranslationKey } from "../i18n/shellDictionary";
import {
  VMetricChip,
  VPanelHeader,
  VStatusChip,
  VStatusStrip,
  VSurface,
  VTooltip,
  type VStatusTone,
} from "../components/vui";
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
import styles from "./AppShellStatusGuidePanel.styles";

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

function systemToneToStatus(tone: SystemStatusTone): VStatusTone {
  if (tone === "running") return "success";
  if (tone === "caution") return "warning";
  if (tone === "failed") return "danger";
  return "neutral";
}

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
  const lifecycleTone = systemToneToStatus(lifecycleStateTone(lifecycleProof?.overallState));

  return (
    <VSurface
      tone="card"
      elevation="flat"
      padding="compact"
      className={styles.statusGuidePanel}
      role="note"
      aria-live="polite"
      ariaLabel={t("systemStatusGuide")}
    >
      <VPanelHeader
        headingLevel={3}
        className={styles.statusGuideHeader}
        title={t("systemStatusGuide")}
        tooltip={t("systemStatusGuideHint")}
        tooltipLabel={t("systemStatusGuide")}
      />
      <div className={styles.statusGuideGrid}>
        {detailCards.map((item) => (
          <VSurface
            key={item.id}
            tone="row"
            elevation="flat"
            padding="compact"
            className={styles.statusGuideCard}
            ariaLabel={`${item.label}: ${item.value}`}
          >
            <VTooltip content={item.note} width="wide">
              <div
                className={styles.statusGuideCardHeader}
                tabIndex={0}
                aria-label={`${item.label}: ${item.value}. ${item.note}`}
              >
                <VMetricChip label={item.label} value={item.value} />
              </div>
            </VTooltip>
            <ul className={styles.statusGuideList}>
              {item.states.map((state) => (
                <VTooltip key={`${item.id}-${state.label}`} content={state.detail} width="wide">
                  <li
                    className={styles.statusGuideListItem}
                    data-current={state.label === item.value ? "true" : undefined}
                    tabIndex={0}
                    aria-label={`${state.label}: ${state.detail}`}
                  >
                    <VStatusChip tone={systemToneToStatus(state.tone)} className={styles.statusGuideStateChip}>
                      {state.label}
                    </VStatusChip>
                  </li>
                </VTooltip>
              ))}
            </ul>
          </VSurface>
        ))}
      </div>
      <VSurface
        tone="row"
        elevation="flat"
        padding="compact"
        className={styles.lifecycleProofCard}
        ariaLabel={t("lifecycleProofTitle")}
      >
        <VPanelHeader
          headingLevel={4}
          className={styles.lifecycleProofHeader}
          title={t("lifecycleProofTitle")}
          tooltip={lifecycleProof?.summary || t("lifecycleProofUnavailable")}
          tooltipLabel={t("lifecycleProofTitle")}
          actions={(
            <VStatusChip tone={lifecycleTone}>
              {lifecycleProof?.overallLabel || t("lifecycleProofUnavailable")}
            </VStatusChip>
          )}
        />
        {lifecycleProof ? (
          <>
            <VStatusStrip
              className={styles.lifecycleProofMeta}
              items={[
                {
                  label: t("lifecycleProofDesiredObserved"),
                  value: `${lifecycleProof.desiredState} / ${lifecycleProof.observedState}`,
                },
                {
                  label: t("lifecycleProofVerifiedAt"),
                  value: lifecycleProof.verifiedAt || "-",
                },
              ]}
            />
            <ul className={styles.lifecycleProofList}>
              {lifecycleProof.components.map((component) => (
                <VTooltip key={component.id} content={component.detail} width="wide">
                  <li
                    className={styles.lifecycleProofItem}
                    tabIndex={0}
                    aria-label={`${component.label}: ${lifecycleStateLabel(component.state, lang)}. ${component.detail}`}
                  >
                    <span className={styles.lifecycleProofName}>{component.label}</span>
                    <VStatusChip tone={systemToneToStatus(lifecycleStateTone(component.state))}>
                      {lifecycleStateLabel(component.state, lang)}
                    </VStatusChip>
                  </li>
                </VTooltip>
              ))}
            </ul>
          </>
        ) : null}
      </VSurface>
    </VSurface>
  );
}
