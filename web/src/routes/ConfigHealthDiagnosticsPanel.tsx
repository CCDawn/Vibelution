import { ExternalLink, RefreshCw } from "lucide-react";

import { type HealthDiagnostics, type HealthFinding, type HealthQuickAction, type LogHelper, type SessionHelper } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./ConfigHealthDiagnosticsPanel.styles";

export type ConfigLanguage = "zh" | "en";

export type ConfigHealthDiagnosticsPanelCopy = {
  healthTitle: string;
  healthBody: string;
  healthLoading: string;
  healthEmpty: string;
  healthRefresh: string;
  healthPriority: string;
  healthQuickActions: string;
  healthEvidence: string;
  healthRecommended: string;
  healthRelatedFindings: string;
  healthNoFindings: string;
  healthOpenLogs: string;
  healthOpenChat: string;
  healthOpenLauncher: string;
  healthOpen: string;
  healthFiles: string;
  healthDirs: string;
  healthSessions: string;
  healthBusy: string;
  healthFailed: string;
  healthStale: string;
  healthPhase: string;
  healthLatest: string;
  healthUpdated: string;
  healthSize: string;
  healthProtected: string;
  healthMaintenanceAvailable: string;
  healthStatusOk: string;
  healthStatusWarning: string;
  healthStatusBlocked: string;
  healthMissing: string;
  healthNotRecorded: string;
};

type ConfigHealthDiagnosticsPanelProps = {
  diagnostics: HealthDiagnostics | undefined;
  loading: boolean;
  lang: ConfigLanguage;
  copy: ConfigHealthDiagnosticsPanelCopy;
  onRefresh: () => void;
};

function formatBytes(size: number) {
  if (!Number.isFinite(size) || size <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTimestamp(value: string, lang: ConfigLanguage, emptyLabel: string) {
  const text = String(value || "").trim();
  if (!text) {
    return emptyLabel;
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function healthStatusLabel(status: string, copy: ConfigHealthDiagnosticsPanelCopy) {
  if (status === "blocked") {
    return copy.healthStatusBlocked;
  }
  if (status === "warning") {
    return copy.healthStatusWarning;
  }
  return copy.healthStatusOk;
}

function healthStatusClassName(status: string) {
  if (status === "blocked") {
    return `${styles.inlineBadge} ${styles.healthBadgeBlocked}`;
  }
  if (status === "warning") {
    return `${styles.inlineBadge} ${styles.inlineBadgeWarning}`;
  }
  return `${styles.inlineBadge} ${styles.statusBadgeReady}`;
}

function healthSeverityClassName(severity: string) {
  if (severity === "blocked") {
    return `${styles.inlineBadge} ${styles.healthBadgeBlocked}`;
  }
  if (severity === "warning") {
    return `${styles.inlineBadge} ${styles.inlineBadgeWarning}`;
  }
  return styles.inlineBadge;
}

function formatFindingId(id: string) {
  return id ? `#${id.replace(/_/g, "-")}` : "";
}

export function ConfigHealthDiagnosticsPanel({
  diagnostics,
  loading,
  lang,
  copy,
  onRefresh,
}: ConfigHealthDiagnosticsPanelProps) {
  const sessionHelpers = diagnostics?.sessionHelpers ?? [];
  const helpers = diagnostics?.logHelpers ?? [];
  const findings = diagnostics?.findings ?? [];
  const priorityFindings = findings.filter((finding) => finding.severity !== "info").slice(0, 4);
  const quickActions = diagnostics?.quickActions ?? [];
  return (
    <section id="config-health-diagnostics" className={styles.sectionSurface}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionHeaderMain}>
          <p className={styles.eyebrow}>{copy.healthTitle}</p>
          <h2 className={styles.sectionTitle}>{copy.healthTitle}</h2>
          <p className={styles.sectionText}>{copy.healthBody}</p>
        </div>
        <div className={styles.sectionHeaderActions}>
          {diagnostics ? (
            <span className={healthStatusClassName(diagnostics.status)}>
              {healthStatusLabel(diagnostics.status, copy)}
            </span>
          ) : null}
          <VButton type="button" className={styles.actionButton} onClick={onRefresh} isDisabled={loading}>
            <RefreshCw size={14} />
            {copy.healthRefresh}
          </VButton>
        </div>
      </div>
      {loading && !diagnostics ? <p className={styles.helperText}>{copy.healthLoading}</p> : null}
      {diagnostics ? (
        <div className={styles.healthSummaryGrid}>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusOk}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.ok}</strong>
          </article>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusWarning}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.warning}</strong>
          </article>
          <article className={styles.matrixCard}>
            <p className={styles.matrixTitle}>{copy.healthStatusBlocked}</p>
            <strong className={styles.healthMetric}>{diagnostics.counts.blocked}</strong>
          </article>
        </div>
      ) : null}
      {diagnostics?.summary ? <p className={styles.sectionText}>{diagnostics.summary}</p> : null}
      {diagnostics ? (
        <div className={styles.healthWorkbenchGrid}>
          <div className={styles.healthPanel}>
            <div className={styles.healthPanelHeader}>
              <h3>{copy.healthPriority}</h3>
              <span className={styles.inlineBadge}>{priorityFindings.length.toLocaleString()}</span>
            </div>
            {priorityFindings.length ? (
              <div className={styles.findingList}>
                {priorityFindings.map((finding) => (
                  <HealthFindingCard key={finding.id} finding={finding} copy={copy} />
                ))}
              </div>
            ) : (
              <p className={styles.helperText}>{copy.healthNoFindings}</p>
            )}
          </div>
          <div className={styles.healthPanel}>
            <div className={styles.healthPanelHeader}>
              <h3>{copy.healthQuickActions}</h3>
              <span className={styles.inlineBadge}>{quickActions.length.toLocaleString()}</span>
            </div>
            {quickActions.length ? (
              <div className={styles.quickActionList}>
                {quickActions.map((action) => (
                  <HealthQuickActionLink key={action.id} action={action} copy={copy} />
                ))}
              </div>
            ) : (
              <p className={styles.helperText}>{copy.healthNoFindings}</p>
            )}
          </div>
        </div>
      ) : null}
      {sessionHelpers.length ? (
        <div className={styles.logHelperGrid}>
          {sessionHelpers.map((helper) => (
            <SessionHelperCard key={helper.id} helper={helper} lang={lang} copy={copy} />
          ))}
        </div>
      ) : null}
      {helpers.length ? (
        <div className={styles.logHelperGrid}>
          {helpers.map((helper) => (
            <LogHelperCard key={helper.id} helper={helper} lang={lang} copy={copy} />
          ))}
        </div>
      ) : !loading ? (
        <p className={styles.helperText}>{copy.healthEmpty}</p>
      ) : null}
    </section>
  );
}

function HealthFindingCard({ finding, copy }: { finding: HealthFinding; copy: ConfigHealthDiagnosticsPanelCopy }) {
  return (
    <article className={styles.findingCard}>
      <div className={styles.findingHeader}>
        <div>
          <p className={styles.matrixTitle}>{formatFindingId(finding.id)}</p>
          <h4>{finding.title}</h4>
        </div>
        <span className={healthSeverityClassName(finding.severity)}>
          {healthStatusLabel(finding.severity, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{finding.summary}</p>
      {finding.evidence.length ? (
        <div className={styles.findingEvidence} aria-label={copy.healthEvidence}>
          {finding.evidence.slice(0, 4).map((item) => (
            <span key={`${finding.id}-${item.label}`}>
              <strong>{item.label}</strong>
              {item.value}
            </span>
          ))}
        </div>
      ) : null}
      {finding.recommendedAction ? (
        <p className={styles.findingRecommendation}>
          <strong>{copy.healthRecommended}</strong>
          {finding.recommendedAction}
        </p>
      ) : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={finding.route || "/logs"}>
          <ExternalLink size={14} />
          {copy.healthOpen}
        </a>
        {finding.resetItemId ? (
          <a className={styles.actionButton} href="/launcher" target="_blank" rel="noreferrer">
            <ExternalLink size={14} />
            {copy.healthOpenLauncher}
          </a>
        ) : null}
      </div>
    </article>
  );
}

function HealthQuickActionLink({ action, copy }: { action: HealthQuickAction; copy: ConfigHealthDiagnosticsPanelCopy }) {
  const href = action.resetItemId ? "/launcher" : action.route || "/logs";
  return (
    <a className={styles.quickActionItem} href={href}>
      <div>
        <span className={healthSeverityClassName(action.severity)}>
          {action.findingId ? formatFindingId(action.findingId) : action.source}
        </span>
        <strong>{action.title}</strong>
        <small>{action.description}</small>
      </div>
      <ExternalLink size={15} />
    </a>
  );
}

function SessionHelperCard({ helper, lang, copy }: { helper: SessionHelper; lang: ConfigLanguage; copy: ConfigHealthDiagnosticsPanelCopy }) {
  const updatedLabel = formatTimestamp(helper.updatedAt, lang, copy.healthNotRecorded);
  return (
    <article className={styles.logHelperCard}>
      <div className={styles.logHelperHeader}>
        <div>
          <p className={styles.matrixTitle}>{helper.activeSessionId || helper.id}</p>
          <h3 className={styles.cardTitle}>{helper.title}</h3>
        </div>
        <span className={healthStatusClassName(helper.status)}>
          {helper.statusLabel || healthStatusLabel(helper.status, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{helper.description}</p>
      <div className={styles.logHelperMetaGrid}>
        <span>
          <strong>{helper.sessionCount.toLocaleString()}</strong>
          {copy.healthSessions}
        </span>
        <span>
          <strong>{helper.busyCount.toLocaleString()}</strong>
          {copy.healthBusy}
        </span>
        <span>
          <strong>{helper.failedCount.toLocaleString()}</strong>
          {copy.healthFailed}
        </span>
        <span>
          <strong>{helper.staleCount.toLocaleString()}</strong>
          {copy.healthStale}
        </span>
        <span title={helper.updatedAt}>
          <strong>{updatedLabel}</strong>
          {copy.healthUpdated}
        </span>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthLatest}</span>
        <strong>{helper.latestSignal || helper.activeTitle || copy.healthMissing}</strong>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthPhase}</span>
        <strong>{helper.currentPhase || copy.healthNotRecorded}</strong>
      </div>
      <p className={styles.cardSubtle}>{helper.recommendedAction}</p>
      <div className={styles.cardBadges}>
        <span className={`${styles.inlineBadge} ${styles.inlineBadgeWarning}`}>{copy.healthProtected}</span>
        {helper.findingIds?.length ? (
          <span className={styles.inlineBadge}>
            {copy.healthRelatedFindings} {helper.findingIds.length}
          </span>
        ) : null}
      </div>
      {helper.protectedReason ? <p className={styles.helperText}>{helper.protectedReason}</p> : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={helper.route || "/chat"}>
          <ExternalLink size={14} />
          {copy.healthOpenChat}
        </a>
      </div>
    </article>
  );
}

function LogHelperCard({ helper, lang, copy }: { helper: LogHelper; lang: ConfigLanguage; copy: ConfigHealthDiagnosticsPanelCopy }) {
  const updatedLabel = formatTimestamp(helper.lastModifiedAt, lang, copy.healthNotRecorded);
  const latestSignal = helper.latestSignal || helper.latestPath || copy.healthMissing;
  return (
    <article className={styles.logHelperCard}>
      <div className={styles.logHelperHeader}>
        <div>
          <p className={styles.matrixTitle}>{helper.rootPath}</p>
          <h3 className={styles.cardTitle}>{helper.title}</h3>
        </div>
        <span className={healthStatusClassName(helper.status)}>
          {helper.statusLabel || healthStatusLabel(helper.status, copy)}
        </span>
      </div>
      <p className={styles.cardSubtle}>{helper.description}</p>
      <div className={styles.logHelperMetaGrid}>
        <span>
          <strong>{helper.fileCount.toLocaleString()}</strong>
          {copy.healthFiles}
        </span>
        <span>
          <strong>{helper.directoryCount.toLocaleString()}</strong>
          {copy.healthDirs}
        </span>
        <span>
          <strong>{formatBytes(helper.sizeBytes)}</strong>
          {copy.healthSize}
        </span>
        <span title={helper.lastModifiedAt}>
          <strong>{updatedLabel}</strong>
          {copy.healthUpdated}
        </span>
      </div>
      <div className={styles.logHelperSignal}>
        <span>{copy.healthLatest}</span>
        <strong>{latestSignal}</strong>
      </div>
      <p className={styles.cardSubtle}>{helper.recommendedAction}</p>
      <div className={styles.cardBadges}>
        <span className={helper.protected ? `${styles.inlineBadge} ${styles.inlineBadgeWarning}` : styles.inlineBadge}>
          {helper.protected ? copy.healthProtected : copy.healthMaintenanceAvailable}
        </span>
        {helper.findingIds?.length ? (
          <span className={styles.inlineBadge}>
            {copy.healthRelatedFindings} {helper.findingIds.length}
          </span>
        ) : null}
      </div>
      {helper.protectedReason ? <p className={styles.helperText}>{helper.protectedReason}</p> : null}
      <div className={styles.actionsRow}>
        <a className={styles.actionButton} href={helper.route || "/logs"}>
          <ExternalLink size={14} />
          {copy.healthOpenLogs}
        </a>
        {helper.resetItemId ? (
          <a className={styles.actionButton} href="/launcher" target="_blank" rel="noreferrer">
            <ExternalLink size={14} />
            {copy.healthOpenLauncher}
          </a>
        ) : null}
      </div>
    </article>
  );
}
