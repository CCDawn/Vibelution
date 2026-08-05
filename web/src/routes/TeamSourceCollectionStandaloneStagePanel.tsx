import { Archive, CheckCircle2, Play, RefreshCw, Search } from "lucide-react";
import { type ReactNode } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VSplitWorkspace } from "../components/vui";
import {
  TeamStageCard,
  TeamStageCommandBar,
  TeamStagePipeline,
  type TeamStageStat,
  type TeamStageTone,
} from "../components/vui/product/team-management";
import styles from "./TeamSourceCollectionStandaloneStagePanel.styles";

export type TeamSourceCollectionStandaloneStageIcon = "play" | "search" | "check" | "archive" | "refresh";

export type TeamSourceCollectionStandaloneStageModule = {
  id: string;
  tone: TeamStageTone;
  selected: boolean;
  title: string;
  status: ReactNode;
  label: ReactNode;
  metric: ReactNode;
  nextLabel: ReactNode;
  actionLabel: ReactNode;
  actionDisabled: boolean;
  actionTitle: string;
  actionIcon: TeamSourceCollectionStandaloneStageIcon;
  onAction: () => void;
  onDetail: () => void;
};

type TeamSourceCollectionStandaloneStagePanelProps = {
  commandAriaLabel: string;
  commandTone: TeamStageTone;
  commandTitle: ReactNode;
  commandSubtitle: ReactNode;
  commandStats: TeamStageStat[];
  searchBrief?: ReactNode;
  runSwitcher: ReactNode;
  runHistoryLabel?: string;
  phaseCloseGate?: ReactNode;
  stagePipelineId: string;
  stagePipelineAriaLabel: string;
  modules: TeamSourceCollectionStandaloneStageModule[];
  activePanel: ReactNode;
  compactActivePanel?: boolean;
};

const SC_LEFT_PANE = {
  id: "sc-left",
  defaultWidth: 320,
  minWidth: 260,
  maxWidth: 440,
} as const;

export function TeamSourceCollectionStageActionIcon({ icon }: { icon: TeamSourceCollectionStandaloneStageIcon }) {
  if (icon === "search") {
    return <Search size={13} />;
  }
  if (icon === "check") {
    return <CheckCircle2 size={13} />;
  }
  if (icon === "archive") {
    return <Archive size={13} />;
  }
  if (icon === "refresh") {
    return <RefreshCw size={13} />;
  }
  return <Play size={13} />;
}

/**
 * Knowledge-collection desktop workbench:
 * command bar + resizable left config rail + main stage workspace
 * (center list / right actions are split inside ActiveStagePanel).
 */
export function TeamSourceCollectionStandaloneStagePanel({
  commandAriaLabel,
  commandTone,
  commandTitle,
  commandSubtitle,
  commandStats,
  searchBrief,
  runSwitcher,
  runHistoryLabel = "切换历史批次",
  phaseCloseGate,
  stagePipelineId,
  stagePipelineAriaLabel,
  modules,
  activePanel,
  compactActivePanel = false,
}: TeamSourceCollectionStandaloneStagePanelProps) {
  return (
    <main
      className={compactActivePanel ? styles.sourceCollectionPageBodyCompact : styles.sourceCollectionPageBody}
      data-testid="source-collection-standalone-workbench"
    >
      <TeamStageCommandBar
        ariaLabel={commandAriaLabel}
        tone={commandTone}
        title={commandTitle}
        subtitle={commandSubtitle}
        stats={commandStats}
      />
      <VSplitWorkspace
        className={styles.sourceCollectionPageSplit}
        data-testid="source-collection-page-split"
        resize={{
          layoutId: WORKBENCH_LAYOUT_IDS.teamsSourceCollection,
          sidebar: SC_LEFT_PANE,
        }}
        sidebar={(
          <aside className={styles.sourceCollectionLeftRail} aria-label={stagePipelineAriaLabel}>
            {searchBrief}
            {phaseCloseGate}
            <TeamStagePipeline id={stagePipelineId} ariaLabel={stagePipelineAriaLabel}>
              {modules.map((module, index) => (
                <TeamStageCard
                  key={module.id}
                  index={index}
                  tone={module.tone}
                  selected={module.selected}
                  title={module.title}
                  onActivate={module.onDetail}
                  status={module.status}
                  label={module.label}
                  metric={module.metric}
                  nextLabel={module.nextLabel}
                />
              ))}
            </TeamStagePipeline>
            {runSwitcher ? (
              <details className={styles.sourceCollectionRunHistory}>
                <summary>{runHistoryLabel}</summary>
                <div className={styles.sourceCollectionRunContext}>
                  {runSwitcher}
                </div>
              </details>
            ) : null}
          </aside>
        )}
        main={(
          <div className={styles.sourceCollectionMainHost} data-vui-region="source-collection-main">
            {activePanel}
          </div>
        )}
      />
    </main>
  );
}
