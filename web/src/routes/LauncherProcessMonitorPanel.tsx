import { VTooltip } from "../components/vui";
import styles from "./LauncherProcessMonitorPanel.styles";

export type LauncherProcessRow = {
  id: string;
  label: string;
  status: string;
  pid: string;
  port: string;
  ownership: string;
  detail: string;
  technical: string;
  ok: boolean;
  tone?: "neutral" | "success" | "warning" | "error";
};

type LauncherProcessMonitorCopy = {
  processMonitor: string;
  processMonitorHint: string;
  unit: string;
  state: string;
  pid: string;
  port: string;
  ownership: string;
  detail: string;
  residualCount: string;
};

type LauncherProcessMonitorPanelProps = {
  copy: LauncherProcessMonitorCopy;
  rows: LauncherProcessRow[];
  residualCount: number;
  selectedId?: string;
};

export function LauncherProcessMonitorPanel({
  copy,
  rows,
  residualCount,
  selectedId = "",
}: LauncherProcessMonitorPanelProps) {
  return (
    <section className={styles.panel} data-vui-region="launcher-process-monitor" aria-label={copy.processMonitor}>
      <div className={styles.panelHeader}>
        <p className={styles.panelEyebrow}>{copy.processMonitor}</p>
        <strong>{residualCount > 0 ? `${copy.residualCount}: ${residualCount}` : copy.processMonitorHint}</strong>
      </div>
      <div className={styles.statusTable} role="table" aria-label={copy.processMonitor}>
        <div className={styles.statusHead} role="row">
          <span role="columnheader">{copy.unit}</span>
          <span role="columnheader">{copy.state}</span>
          <span role="columnheader">{copy.pid}</span>
          <span role="columnheader">{copy.port}</span>
          <span role="columnheader">{copy.ownership}</span>
          <span role="columnheader">{copy.detail}</span>
        </div>
        {rows.map((row) => (
          <VTooltip key={row.id} content={row.technical} width="wide">
            <div
              className={styles.statusRow}
              role="row"
              data-tone={row.tone || "neutral"}
              data-selected={selectedId && (row.id === selectedId || row.id.startsWith(`${selectedId}-`)) ? "true" : "false"}
              tabIndex={0}
            >
              <span role="cell"><strong>{row.label}</strong></span>
              <span role="cell">{row.status}</span>
              <span role="cell">{row.pid}</span>
              <span role="cell">{row.port}</span>
              <span role="cell">{row.ownership}</span>
              <span role="cell">{row.detail}</span>
            </div>
          </VTooltip>
        ))}
      </div>
    </section>
  );
}
