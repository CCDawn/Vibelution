import type { NodeHandoffRecord, ResearchBudgetProjection, EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import type { KnowledgeInvocationBadge, ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { VButton, VEmptyState, VSurface } from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import type { NodeAdapterSpec } from "./nodeAdapterModel";
import { NodeAgentSection } from "./NodeAgentSection";
import { NodeCommandSection } from "./NodeCommandSection";
import { NodeHandoffSection } from "./NodeHandoffSection";
import { NodeKnowledgeCollectionSection } from "./NodeKnowledgeCollectionSection";
import { NodeSessionSection } from "./NodeSessionSection";
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
  /** Historical formal nodes expose evidence only; the current task owns writes. */
  isCurrentTask?: boolean;
  /** Formal runtime primary actions are rendered by the fixed workspace footer. */
  primaryActionOwnedByWorkspace?: boolean;
  onOffer: (offer: CommandOffer) => Promise<void>;
  hideStartOffer?: boolean;
  statusBanner?: string | null;
  hypothesisNavLabel?: string | null;
  onNavigateHypothesis?: () => void;
  collectionRecoveryRequestId?: string;
  collectionRecoveryLabel?: string;
  onRecoverCollection?: (requestId: string) => Promise<void>;
  collectionRecoveryBusy?: boolean;
  collectionRecoveryError?: string | null;
  /** Knowledge sideflow aggregate for this node; `undefined` hides the whole
   * section (definitions without a sideflow region), `null` means the
   * not-yet-started state with its request preview. */
  knowledgeBadge?: KnowledgeInvocationBadge | null;
  /** Snapshot-level offers carry the knowledge commands (ensure/inspect). */
  knowledgeOffers?: CommandOffer[];
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
  const isCurrentTask = props.isCurrentTask !== false;
  const offers = props.hideStartOffer
    ? withoutStartNodeOffers(detail.commandOffers)
    : (detail.commandOffers ?? []);
  const selectedPrimaryOffer = isCurrentTask && adapter.actorKind === "agent"
    ? pickPrimaryCommandOffer(offers)
    : null;
  const primaryOffer = props.primaryActionOwnedByWorkspace ? null : selectedPrimaryOffer;
  const restOffers = props.primaryActionOwnedByWorkspace
    ? []
    : isCurrentTask && adapter.actorKind === "agent"
      ? remainingCommandOffers(offers, selectedPrimaryOffer)
      : isCurrentTask ? offers : [];
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
          readOnly={!isCurrentTask}
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
      {adapter.actorKind === "agent" ? <NodeSessionSection detail={detail} /> : null}
      {!isCurrentTask ? (
        <p className={styles.status} role="note" data-testid="node-inspector-readonly">
          {isZh ? "历史节点只读；请前往当前任务执行操作。" : "Historical node is read-only; go to the current task to act."}
        </p>
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
      {props.nodeId === "source_finding"
        && props.collectionRecoveryRequestId
        && props.onRecoverCollection ? (
        <div className={styles.nav} data-testid="source-finding-collection-recovery">
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            isDisabled={props.collectionRecoveryBusy}
            onPress={() => props.onRecoverCollection?.(props.collectionRecoveryRequestId || "")}
          >
            {props.collectionRecoveryBusy
              ? (isZh ? "正在恢复搜集…" : "Recovering collection…")
              : (props.collectionRecoveryLabel || (isZh ? "恢复搜集" : "Recover collection"))}
          </VButton>
          {props.collectionRecoveryBusy ? (
            <div role="status" className={styles.status}>
              {isZh ? "正在绑定资料搜集子运行并启动搜索" : "Binding the collection run and starting search"}
            </div>
          ) : null}
          {props.collectionRecoveryError ? (
            <div role="alert" className={styles.status}>
              {isZh ? "恢复搜集失败：" : "Collection recovery failed: "}{props.collectionRecoveryError}
            </div>
          ) : null}
        </div>
      ) : null}
      <NodeHandoffSection
        handoffs={props.handoffs ?? []}
        pending={props.handoffPending}
        blockedReason={detail.blockedReason || ""}
        lang={lang}
      />
      {props.knowledgeBadge !== undefined ? (
        <NodeKnowledgeCollectionSection
          badge={props.knowledgeBadge}
          offers={props.knowledgeOffers ?? []}
          busy={props.busy}
          onOffer={props.onOffer}
          lang={lang}
        />
      ) : null}
      {/* When the primary action itself is blocked, secondary run commands
          (retry/rebind) are noise that buries the blocker reason — hide them
          until the primary becomes actionable (GitHub Actions shows one
          disabled primary with its reason, not a row of dead buttons). */}
      <NodeCommandSection
        offers={!primaryOffer || primaryOffer.available ? restOffers : []}
        busy={props.busy}
        onOffer={props.onOffer}
        lang={lang}
        runVersion={detail.runVersion}
      />
    </VSurface>
  );
}
