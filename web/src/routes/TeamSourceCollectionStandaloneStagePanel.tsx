import { Archive, CheckCircle2, Play, RefreshCw, Search } from "lucide-react";
import { type ReactNode } from "react";

import { VNativeButton } from "../components/vui";
import {
  TeamStageCard,
  TeamStageCommandBar,
  TeamStagePipeline,
  type TeamStageStat,
  type TeamStageTone,
} from "../components/vui/product/team-management";
import styles from "./TeamsRoute.styles";

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
  runSwitcher: ReactNode;
  stagePipelineId: string;
  stagePipelineAriaLabel: string;
  modules: TeamSourceCollectionStandaloneStageModule[];
  activePanel: ReactNode;
};

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

export function TeamSourceCollectionStandaloneStagePanel({
  commandAriaLabel,
  commandTone,
  commandTitle,
  commandSubtitle,
  commandStats,
  runSwitcher,
  stagePipelineId,
  stagePipelineAriaLabel,
  modules,
  activePanel,
}: TeamSourceCollectionStandaloneStagePanelProps) {
  return (
    <main className={styles.sourceCollectionPageBody}>
      <TeamStageCommandBar
        ariaLabel={commandAriaLabel}
        tone={commandTone}
        title={commandTitle}
        subtitle={commandSubtitle}
        stats={commandStats}
      />
      {runSwitcher}
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
            actions={
              <VNativeButton
                type="button"
                disabled={module.actionDisabled}
                onClick={module.onAction}
                title={module.actionTitle}
              >
                <TeamSourceCollectionStageActionIcon icon={module.actionIcon} />
                {module.actionLabel}
              </VNativeButton>
            }
          />
        ))}
      </TeamStagePipeline>
      <div className={styles.sourceCollectionPageGrid}>
        {activePanel}
      </div>
    </main>
  );
}
