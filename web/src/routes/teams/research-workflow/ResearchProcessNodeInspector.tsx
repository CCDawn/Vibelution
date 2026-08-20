import type { NodeHandoffRecord, ResearchBudgetProjection, EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { VButton, VEmptyState, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import type { NodeAdapterSpec } from "./nodeAdapterModel";
import { NodeAgentSection } from "./NodeAgentSection";
import { NodeCommandSection } from "./NodeCommandSection";
import { NodeHandoffSection } from "./NodeHandoffSection";
import {
  isHypothesisFirstMeetingBlocker,
  pickPrimaryCommandOffer,
  remainingCommandOffers,
  withoutStartNodeOffers,
} from "./nodeInspectorOpsModel";
import { researchActorLabel, researchStageLabel } from "./researchNodePresentation";
import styles from "./ResearchProcessNodeInspector.styles";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";

export type ResearchProcessNodeInspectorProps = {
  teamId: string;
  nodeId: string | null;
  adapter: NodeAdapterSpec | null;
  detail: ResearchWorkflowNodeDetail | null;
  effectiveBindings: EffectiveAgentBinding[] | null;
  budget: ResearchBudgetProjection | null;
  handoffs?: NodeHandoffRecord[];
  handoffPending: boolean;
  busy: boolean;
  onOffer: (offer: CommandOffer) => Promise<void>;
  hideStartOffer?: boolean;
  statusBanner?: string | null;
  hypothesisNavLabel?: string | null;
  onNavigateHypothesis?: () => void;
};

export function ResearchProcessNodeInspector(props: ResearchProcessNodeInspectorProps) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  if (!props.adapter || !props.nodeId) {
    return (
      <div className={styles.centered} data-vui="node-inspector-empty">
        <VEmptyState title={isZh ? "选择流程节点" : "Select a workflow node"} className={styles.empty}>
          {isZh
            ? "在画布上点击任务节点，查看绑定、会话与运行命令。"
            : "Click a task node on the canvas to inspect bindings, sessions, and run commands."}
        </VEmptyState>
      </div>
    );
  }
  if (!props.detail) {
    return (
      <div className={styles.centered}>
        <VEmptyState title={isZh ? "暂无节点运行数据" : "No node run data yet"} className={styles.empty} />
      </div>
    );
  }

  const { adapter, detail } = props;
  const offers = props.hideStartOffer
    ? withoutStartNodeOffers(detail.commandOffers)
    : (detail.commandOffers ?? []);
  const primaryOffer = adapter.actorKind === "agent"
    ? pickPrimaryCommandOffer(offers)
    : null;
  const restOffers = adapter.actorKind === "agent"
    ? remainingCommandOffers(offers, primaryOffer)
    : offers;
  const showHypothesisNav = Boolean(
    props.onNavigateHypothesis
    && (props.hypothesisNavLabel || (primaryOffer && isHypothesisFirstMeetingBlocker(primaryOffer))),
  );

  return (
    <VSurface tone="panel" className={styles.root} data-vui="node-inspector">
      {adapter.actorKind === "agent" ? (
        <NodeAgentSection
          teamId={props.teamId}
          stageId={adapter.stageId}
          stageLabel={researchStageLabel(adapter.stageId)}
          detail={detail}
          effectiveBindings={props.effectiveBindings}
          budget={props.budget}
          primaryOffer={primaryOffer}
          busy={props.busy}
          onOffer={props.onOffer}
          lang={lang}
        />
      ) : (
        <header>
          <div className={styles.stage}>{researchStageLabel(adapter.stageId)}</div>
          <h3 className={styles.title}>{detail.label || adapter.label}</h3>
          <div className={styles.meta}>{researchActorLabel(adapter.actorKind)}</div>
        </header>
      )}
      {props.statusBanner ? (
        <div role="status" className={styles.status}>{props.statusBanner}</div>
      ) : null}
      {showHypothesisNav ? (
        <div className={styles.nav}>
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            onPress={() => props.onNavigateHypothesis?.()}
          >
            {props.hypothesisNavLabel || (isZh ? "前往闭环首轮假说讨论" : "Go to the first hypothesis discussion")}
          </VButton>
        </div>
      ) : null}
      <NodeHandoffSection
        handoffs={props.handoffs ?? []}
        pending={props.handoffPending}
        blockedReason={detail.blockedReason || ""}
        lang={lang}
      />
      {/* When the primary action itself is blocked, secondary run commands
          (retry/rebind) are noise that buries the blocker reason — hide them
          until the primary becomes actionable (GitHub Actions shows one
          disabled primary with its reason, not a row of dead buttons). */}
      <NodeCommandSection
        offers={!primaryOffer || primaryOffer.available ? restOffers : []}
        busy={props.busy}
        onOffer={props.onOffer}
        lang={lang}
      />
    </VSurface>
  );
}
