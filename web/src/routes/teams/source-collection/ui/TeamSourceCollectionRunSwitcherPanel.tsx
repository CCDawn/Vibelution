import { Search } from "lucide-react";

import { VNativeButton, VStringSelect, VTooltip } from "../../../../components/vui";
import styles from "./TeamSourceCollectionRunSwitcherPanel.styles";

type TeamSourceCollectionRunSwitcherLang = "zh" | "en";

export type TeamSourceCollectionRunSwitcherRun = {
  runId: string;
  label: string;
};

type TeamSourceCollectionRunSwitcherPanelProps = {
  lang: TeamSourceCollectionRunSwitcherLang;
  runs: TeamSourceCollectionRunSwitcherRun[];
  selectedRunId: string;
  hint: string;
  recordMetric: string | number;
  candidateMetric: string | number;
  statusLabel: string;
  canSwitchToHistoricalRun: boolean;
  onRunChange: (runId: string) => void;
  onSwitchToHistoricalRun: () => void;
};

export function TeamSourceCollectionRunSwitcherPanel({
  lang,
  runs,
  selectedRunId,
  hint,
  recordMetric,
  candidateMetric,
  statusLabel,
  canSwitchToHistoricalRun,
  onRunChange,
  onSwitchToHistoricalRun,
}: TeamSourceCollectionRunSwitcherPanelProps) {
  if (!runs.length) {
    return null;
  }
  const isZh = lang === "zh";

  return (
    <section className={styles.sourceCollectionRunSwitcher} aria-label={isZh ? "资料批次选择" : "Source collection run selector"}>
      <label className={styles.sourceCollectionRunSwitcherMain}>
        <span>{isZh ? "当前批次" : "Run"}</span>
        <VTooltip content={hint} width="wide">
          <VStringSelect
            ariaLabel={lang === "zh" ? "选择批次" : "Select run"}
            value={selectedRunId}
            isDisabled={!runs.length}
            onValueChange={onRunChange}
            options={runs.map((run) => ({
              value: run.runId,
              label: run.label,
            }))}
          />
        </VTooltip>
      </label>
      <div className={styles.sourceCollectionRunSwitcherStats}>
        <span>
          {isZh ? "资料" : "records"} <strong>{recordMetric}</strong>
        </span>
        <span>
          {isZh ? "候选" : "candidates"} <strong>{candidateMetric}</strong>
        </span>
        <span>
          {isZh ? "状态" : "status"} <strong>{statusLabel}</strong>
        </span>
      </div>
      {canSwitchToHistoricalRun ? (
        <VNativeButton type="button" onClick={onSwitchToHistoricalRun}>
          <Search size={13} />
          {isZh ? "切换到有资料批次" : "Show run with records"}
        </VNativeButton>
      ) : null}
    </section>
  );
}
