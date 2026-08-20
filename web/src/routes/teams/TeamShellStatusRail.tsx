import { VButton, VNativeButton, VStatusChip, VSurface } from "../../components/vui";
import styles from "./TeamShellStatusRail.styles";
import {
  teamShellStageChipTone,
  type TeamShellStatusNode,
  type TeamShellStatusStage,
} from "./teamShellStatusModel";

export type TeamShellStatusRailProps = {
  lang: "zh" | "en";
  nextTitle: string;
  nextBody: string;
  cta?: string;
  ctaDisabled?: boolean;
  onCta?: () => void;
  stages: TeamShellStatusStage[];
  nodes?: TeamShellStatusNode[];
  selectedNodeId?: string | null;
  onSelectNode?: (nodeId: string) => void;
};

/**
 * Left rail after team pick moved to the toolbar: next step, stage index, node status.
 * Width still belongs to VBoardWorkbenchPage / VCanvasWorkbenchPage + layoutId.
 */
export function TeamShellStatusRail({
  lang,
  nextTitle,
  nextBody,
  cta,
  ctaDisabled = false,
  onCta,
  stages,
  nodes = [],
  selectedNodeId = null,
  onSelectNode,
}: TeamShellStatusRailProps) {
  return (
    <VSurface
      as="aside"
      tone="rail"
      elevation="flat"
      padding="compact"
      className={styles.root}
      data-testid="team-shell-status-rail"
      data-vui="team-shell-status-rail"
      data-vui-region="teams-sidebar"
      aria-label={lang === "zh" ? "团队状态" : "Team status"}
    >
      <div className={styles.body}>
        <VSurface tone="panel" padding="compact" className={styles.nextCard} data-testid="status-rail-next">
          <span className={styles.nextKicker}>{lang === "zh" ? "下一步" : "Next"}</span>
          <strong className={styles.nextTitle}>{nextTitle}</strong>
          <p className={styles.nextBody}>{nextBody}</p>
          {cta ? (
            <VButton
              type="button"
              density="compact"
              variant="primary"
              isDisabled={ctaDisabled}
              onPress={onCta}
            >
              {cta}
            </VButton>
          ) : null}
        </VSurface>
        {stages.length ? (
          <div className={styles.stageList} data-testid="status-rail-stages">
            <h2 className={styles.sectionLabel}>{lang === "zh" ? "阶段" : "Stages"}</h2>
            {stages.map((stage) => (
              <div
                key={stage.id}
                className={stage.tone === "active" ? styles.stageItemActive : styles.stageItem}
                data-testid={`status-rail-stage-${stage.id}`}
              >
                <strong className={styles.stageTitle}>{stage.title}</strong>
                <VStatusChip tone={teamShellStageChipTone(stage.tone)}>{stage.status}</VStatusChip>
              </div>
            ))}
          </div>
        ) : null}
        {nodes.length ? (
          <div className={styles.nodeIndex} data-testid="status-rail-nodes">
            <h2 className={styles.sectionLabel}>{lang === "zh" ? "节点" : "Nodes"}</h2>
            {nodes.map((item) => {
              const selected = selectedNodeId === item.id;
              return (
                <VNativeButton
                  key={item.id}
                  type="button"
                  className={selected ? styles.nodeItemActive : styles.nodeItem}
                  aria-pressed={selected}
                  data-testid={`status-rail-node-${item.id}`}
                  onClick={() => onSelectNode?.(item.id)}
                >
                  <strong className={styles.stageTitle}>{item.label}</strong>
                  <VStatusChip tone={item.statusTone}>{item.status}</VStatusChip>
                  <span className={styles.nodeAgent}>{item.agent}</span>
                </VNativeButton>
              );
            })}
          </div>
        ) : null}
      </div>
    </VSurface>
  );
}
