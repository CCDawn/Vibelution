import { LoaderCircle, RefreshCw } from "lucide-react";

import { VButton } from "../components/vui";
import { launcherRouteStyles as styles } from "./LauncherRoute.styles";

export type LauncherDiagnosticsSpecItem = {
  label: string;
  value: string;
};

export type LauncherDiagnosticsListItem = {
  id?: string;
  primary: string;
  secondary?: string;
  tone?: "neutral" | "success" | "warning" | "error";
};

export type LauncherDiagnosticsLineItem = {
  label: string;
  value: string;
  meta: string;
  tone?: "neutral" | "success" | "warning" | "error";
};

export type LauncherGuardianResponsibilityRow = {
  id: string;
  label: string;
  owner: string;
  state: string;
  detail: string;
  tone: string;
};

type LauncherDiagnosticsCopy = {
  advancedDiagnostics: string;
  controlEvidence: string;
  controlPlane: string;
  detail: string;
  diagnosticsCollapsedHint: string;
  guardian: string;
  legacyAdapter: string;
  maintenanceDetails: string;
  maintenanceScopeSummary: string;
  owned: string;
  queueAndEvents: string;
  reattachSupervisor: string;
  state: string;
  unit: string;
};

type LauncherDiagnosticsPanelProps = {
  copy: LauncherDiagnosticsCopy;
  controlPlaneStatus: string;
  controlPlaneSpecs: LauncherDiagnosticsSpecItem[];
  controlEvidenceStatus: string;
  controlEvidenceSpecs: LauncherDiagnosticsSpecItem[];
  recoveryLine: LauncherDiagnosticsLineItem | null;
  activeCommandLine: LauncherDiagnosticsLineItem;
  queueItemCount: number;
  queueItems: LauncherDiagnosticsListItem[];
  guardianProgress: string;
  guardianOwnedCount: number;
  guardianAdapterCount: number;
  guardianRows: LauncherGuardianResponsibilityRow[];
  diagnosticSpecs: LauncherDiagnosticsSpecItem[];
  busy: boolean;
  canRequestSupervisorReattach: boolean;
  supervisorPending: boolean;
  onReattachSupervisor: () => void;
};

function Spec({ label, value }: LauncherDiagnosticsSpecItem) {
  return (
    <>
      <dt>{label}</dt>
      <dd title={value}>{value}</dd>
    </>
  );
}

function CompactList({ items }: { items: LauncherDiagnosticsListItem[] }) {
  return (
    <div className={styles.compactList}>
      {items.length ? items.map((item) => (
        <div key={item.id || item.primary} className={styles.compactItem} data-tone={item.tone}>
          <strong>{item.primary}</strong>
          <small>{item.secondary || "-"}</small>
        </div>
      )) : <small>-</small>}
    </div>
  );
}

export function LauncherDiagnosticsPanel({
  copy,
  controlPlaneStatus,
  controlPlaneSpecs,
  controlEvidenceStatus,
  controlEvidenceSpecs,
  recoveryLine,
  activeCommandLine,
  queueItemCount,
  queueItems,
  guardianProgress,
  guardianOwnedCount,
  guardianAdapterCount,
  guardianRows,
  diagnosticSpecs,
  busy,
  canRequestSupervisorReattach,
  supervisorPending,
  onReattachSupervisor,
}: LauncherDiagnosticsPanelProps) {
  return (
    <details className={`${styles.panel} ${styles.diagnosticsPanel}`}>
      <summary>
        <span>{copy.advancedDiagnostics}</span>
        <strong>{copy.diagnosticsCollapsedHint}</strong>
      </summary>
      <div className={styles.diagnosticsBody}>
        <section className={styles.diagnosticSection}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.controlPlane}</p>
            <strong>{controlPlaneStatus}</strong>
          </div>
          <dl className={styles.specGrid}>
            {controlPlaneSpecs.map((item) => (
              <Spec key={item.label} {...item} />
            ))}
          </dl>
        </section>
        <section className={styles.diagnosticSection}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.controlEvidence}</p>
            <strong>{controlEvidenceStatus}</strong>
          </div>
          <dl className={styles.specGrid}>
            {controlEvidenceSpecs.map((item) => (
              <Spec key={item.label} {...item} />
            ))}
          </dl>
          {recoveryLine ? (
            <div className={styles.recoveryLine} data-tone={recoveryLine.tone}>
              <span>{recoveryLine.label}</span>
              <strong>{recoveryLine.value}</strong>
              <small>{recoveryLine.meta}</small>
            </div>
          ) : null}
          <div className={styles.commandLine}>
            <span>{activeCommandLine.label}</span>
            <strong>{activeCommandLine.value}</strong>
            <small>{activeCommandLine.meta}</small>
          </div>
        </section>
        <section className={styles.diagnosticSection}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.queueAndEvents}</p>
            <strong>{queueItemCount}</strong>
          </div>
          <CompactList items={queueItems} />
        </section>
        <section className={styles.diagnosticSection}>
          <div className={styles.panelHeader}>
            <p className={styles.panelEyebrow}>{copy.maintenanceDetails}</p>
            <strong>{guardianProgress}</strong>
          </div>
          <div className={styles.guardianSummary}>
            <span>{copy.maintenanceScopeSummary}</span>
            <strong>{copy.owned}: {guardianOwnedCount}</strong>
            <strong>{copy.legacyAdapter}: {guardianAdapterCount}</strong>
            <VButton
              type="button"
              variant="secondary"
              className={styles.iconButton}
              onPress={onReattachSupervisor}
              isDisabled={busy || !canRequestSupervisorReattach}
              title={copy.reattachSupervisor}
              icon={supervisorPending ? <LoaderCircle size={15} className={styles.spin} /> : <RefreshCw size={15} />}
            >
              <span>{copy.reattachSupervisor}</span>
            </VButton>
          </div>
          <div className={styles.guardianTable} role="table" aria-label={copy.guardian}>
            <div className={styles.guardianHead} role="row">
              <span role="columnheader">{copy.unit}</span>
              <span role="columnheader">owner</span>
              <span role="columnheader">{copy.state}</span>
              <span role="columnheader">{copy.detail}</span>
            </div>
            {guardianRows.map((item) => (
              <div key={item.id} className={styles.guardianRow} role="row" data-tone={item.tone}>
                <span role="cell"><strong>{item.label}</strong></span>
                <span role="cell">{item.owner}</span>
                <span role="cell">{item.state}</span>
                <span role="cell">{item.detail}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
      <dl className={styles.diagnosticsGrid}>
        {diagnosticSpecs.map((item) => (
          <Spec key={item.label} {...item} />
        ))}
      </dl>
    </details>
  );
}
