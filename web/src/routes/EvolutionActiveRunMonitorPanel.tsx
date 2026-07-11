import {
  Activity,
  CheckCircle2,
  Clock3,
  Gauge,
  LibraryBig,
  LoaderCircle,
  Square,
  TriangleAlert,
} from "lucide-react";

import { VButton } from "../components/vui";
import { type SupervisedRunControlSummary } from "./supervisedRunSummary";
import styles from "./EvolutionActiveRunMonitorPanel.styles";

export type EvolutionActiveRunMonitorMetric = {
  id: string;
  label: string;
  title?: string;
  value: string | number;
};

export type EvolutionActiveRunMonitorEventItem = {
  key: string;
  statusLabel: string;
  summary: string;
  timestamp: string;
  title: string;
};

export type EvolutionActiveRunMonitorAction = {
  disabled?: boolean;
  label: string;
  onClick: () => void;
  title?: string;
};

export type EvolutionActiveRunClosedLoopLedger = {
  action: EvolutionActiveRunMonitorAction;
  description: string;
  evidence: EvolutionActiveRunMonitorMetric[];
  eyebrow: string;
  statusLabel: string;
  statusTone: "primary" | "secondary";
  title: string;
};

export type EvolutionActiveRunMonitorHeader = {
  eyebrow: string;
  fallbackStatusLabel: string;
  sourceKindLabel?: string;
  statusLabel?: string;
  title: string;
  titleTooltip?: string;
};

export type EvolutionActiveRunMonitorRunView = {
  controlSummary: {
    decision?: string;
    headline: string;
    nextAction?: string;
    nextActionLabel: string;
    reason?: string;
    status: string;
    tone?: SupervisedRunControlSummary["tone"];
  };
  error?: string | null;
  events: EvolutionActiveRunMonitorEventItem[];
  feedback?: string | null;
  metrics: EvolutionActiveRunMonitorMetric[];
  openSessionAction?: EvolutionActiveRunMonitorAction | null;
  termination: {
    ariaLabel: string;
    disabled: boolean;
    onClick: () => void;
    pending: boolean;
    title: string;
  };
  timelineTitle: string;
  warning?: string | null;
};

export type EvolutionActiveRunMonitorIdleView = {
  closedLoop?: EvolutionActiveRunClosedLoopLedger | null;
  latestRunAction: EvolutionActiveRunMonitorAction;
  libraryAction: EvolutionActiveRunMonitorAction;
  metrics: EvolutionActiveRunMonitorMetric[];
  notice: string;
  related: EvolutionActiveRunMonitorMetric[];
};

type EvolutionActiveRunMonitorPanelProps = {
  ariaHidden?: boolean;
  className: string;
  header: EvolutionActiveRunMonitorHeader;
  idle: EvolutionActiveRunMonitorIdleView;
  run: EvolutionActiveRunMonitorRunView | null;
};

const RUN_SUMMARY_TONE_CLASS: Record<SupervisedRunControlSummary["tone"], string> = {
  running: styles.runSummaryTone_running,
  success: styles.runSummaryTone_success,
  warning: styles.runSummaryTone_warning,
  danger: styles.runSummaryTone_danger,
  idle: styles.runSummaryTone_idle,
};

function statusIcon(status: string, decision = "") {
  const normalized = String(status).trim().toLowerCase();
  const normalizedDecision = String(decision).trim().toUpperCase();
  if (normalizedDecision === "INCONCLUSIVE") {
    return <TriangleAlert size={16} />;
  }
  if (normalized === "success") {
    return <CheckCircle2 size={16} />;
  }
  if (normalized === "failed" || normalized === "caution") {
    return <TriangleAlert size={16} />;
  }
  if (normalized === "running" || normalized === "waiting" || normalized === "queued" || normalized === "paused" || normalized === "stopping") {
    return <Clock3 size={16} />;
  }
  if (normalized === "done" || normalized === "cancelled") {
    return <CheckCircle2 size={16} />;
  }
  return <Gauge size={16} />;
}

function renderMetric(metric: EvolutionActiveRunMonitorMetric, className: string) {
  return (
    <article key={metric.id} className={className}>
      <span>{metric.label}</span>
      <strong title={metric.title}>{metric.value}</strong>
    </article>
  );
}

function EvolutionActiveRunClosedLoopLedgerPanel({
  ledger,
}: {
  ledger: EvolutionActiveRunClosedLoopLedger;
}) {
  return (
    <div className={styles.closedLoopLedger}>
      <div className={styles.closedLoopLedgerHeader}>
        <div>
          <span className={styles.eyebrow}>{ledger.eyebrow}</span>
          <strong className={styles.truncateText} title={ledger.title}>
            {ledger.title}
          </strong>
        </div>
        <span className={ledger.statusTone === "primary" ? styles.statusPill : styles.secondaryPill}>
          {ledger.statusLabel}
        </span>
      </div>
      <p>{ledger.description}</p>
      <div className={styles.closedLoopLedgerEvidenceGrid}>
        {ledger.evidence.map((item) => renderMetric(item, ""))}
      </div>
      <div className={styles.actionRow}>
        <VButton
          type="button"
          className={styles.inlineAction}
          isDisabled={ledger.action.disabled}
          onClick={ledger.action.onClick}
          title={ledger.action.title}
        >
          <LibraryBig size={15} />
          {ledger.action.label}
        </VButton>
      </div>
    </div>
  );
}

export function EvolutionActiveRunMonitorPanel({
  ariaHidden = false,
  className,
  header,
  idle,
  run,
}: EvolutionActiveRunMonitorPanelProps) {
  return (
    <section className={className} aria-hidden={ariaHidden}>
      <div className={styles.surfaceHeaderCompact}>
        <div>
          <p className={styles.eyebrow}>{header.eyebrow}</p>
          <h2 className={`${styles.sectionTitle} ${styles.truncateText}`} title={header.titleTooltip}>
            {header.title}
          </h2>
        </div>
        {run ? (
          <div className={styles.liveStatusRow}>
            {header.statusLabel ? <span className={styles.statusPill}>{header.statusLabel}</span> : null}
            {header.sourceKindLabel ? <span className={styles.secondaryPill}>{header.sourceKindLabel}</span> : null}
          </div>
        ) : (
          <span className={styles.secondaryPill}>{header.fallbackStatusLabel}</span>
        )}
      </div>

      {run ? (
        <div className={styles.runMonitorDense}>
          <div className={styles.liveRunToolbar}>
            <div className={styles.compactActionGroup}>
              <VButton
                type="button"
                variant="danger"
                className={styles.compactIconAction}
                isDisabled={run.termination.disabled || run.termination.pending}
                title={run.termination.title}
                onClick={run.termination.onClick}
                aria-label={run.termination.ariaLabel}
              >
                {run.termination.pending ? <LoaderCircle size={15} /> : <Square size={15} />}
              </VButton>
            </div>
            <div className={styles.compactActionGroup}>
              {run.openSessionAction ? (
                <VButton
                  type="button"
                  className={styles.compactTextAction}
                  isDisabled={run.openSessionAction.disabled}
                  onClick={run.openSessionAction.onClick}
                  title={run.openSessionAction.title}
                >
                  <Activity size={15} />
                  {run.openSessionAction.label}
                </VButton>
              ) : null}
            </div>
          </div>

          {run.feedback ? <p className={styles.feedbackTextCompact}>{run.feedback}</p> : null}
          {run.error ? <p className={styles.errorTextCompact}>{run.error}</p> : null}
          {run.warning ? <p className={styles.noticeTextCompact}>{run.warning}</p> : null}

          <div className={styles.monitorSummary}>
            <div className={`${styles.liveSummaryRow} ${run.controlSummary.tone ? RUN_SUMMARY_TONE_CLASS[run.controlSummary.tone] : ""}`}>
              <span className={styles.statusIcon}>{statusIcon(run.controlSummary.status, run.controlSummary.decision)}</span>
              <div className={styles.runControlSummaryBody}>
                <p className={styles.heroSummary}>{run.controlSummary.headline}</p>
                {run.controlSummary.reason ? (
                  <p className={styles.runControlReason}>{run.controlSummary.reason}</p>
                ) : null}
              </div>
            </div>
            {run.controlSummary.nextAction ? (
              <div className={styles.runNextActionStrip}>
                <strong>{run.controlSummary.nextActionLabel}</strong>
                <span>{run.controlSummary.nextAction}</span>
              </div>
            ) : null}
          </div>

          <div className={styles.monitorMetricsDense}>
            {run.metrics.map((metric) => renderMetric(metric, styles.metricTile))}
          </div>

          <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
            <h3>{run.timelineTitle}</h3>
            <div className={`${styles.eventList} ${styles.eventListScrollable}`}>
              {run.events.map((event) => (
                <article key={event.key} className={styles.eventRow}>
                  <div className={styles.eventHeader}>
                    <strong>{event.title}</strong>
                    <span className={styles.secondaryPill}>{event.statusLabel}</span>
                  </div>
                  <p className={styles.eventSummary}>{event.summary}</p>
                  <span className={styles.formHint}>{event.timestamp}</span>
                </article>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div className={styles.idleMonitor}>
          <p className={styles.noticeText}>{idle.notice}</p>
          {idle.closedLoop ? <EvolutionActiveRunClosedLoopLedgerPanel ledger={idle.closedLoop} /> : null}
          <div className={styles.metricStrip}>
            {idle.metrics.map((metric) => renderMetric(metric, styles.stripItem))}
          </div>
          <div className={styles.relatedList}>
            {idle.related.map((metric) => renderMetric(metric, styles.relatedRow))}
          </div>
          <div className={styles.actionRow}>
            <VButton
              type="button"
              className={styles.inlineAction}
              isDisabled={idle.latestRunAction.disabled}
              onClick={idle.latestRunAction.onClick}
              title={idle.latestRunAction.title}
            >
              <Activity size={15} />
              {idle.latestRunAction.label}
            </VButton>
            <VButton
              type="button"
              className={styles.inlineAction}
              isDisabled={idle.libraryAction.disabled}
              onClick={idle.libraryAction.onClick}
              title={idle.libraryAction.title}
            >
              <LibraryBig size={15} />
              {idle.libraryAction.label}
            </VButton>
          </div>
        </div>
      )}
    </section>
  );
}
