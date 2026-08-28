/**
 * Inspector section for the knowledge sideflow (补充知识) hanging off a
 * main-chain node. Renders the four server-derived states plus failure
 * recovery from the snapshot's `invocationBadges`, and its actions come from
 * the canonical knowledge command offers — operator-gated offers render as a
 * disabled button with its authorization reason instead of a 403.
 */
import type { KnowledgeInvocationBadge } from "../../../api/types/research-workflow/core";
import {
  isOperatorGatedOffer,
  type CommandOffer,
} from "../../../api/types/research-workflow/commands";
import { KNOWLEDGE_SIDEFLOW_NODE_IDS } from "../../../api/types/researchWorkflow";
import { VButton, VChip } from "../../../components/vui";
import {
  buildKnowledgeCollectionInspectorModel,
  type KnowledgeCollectionInspectorModel,
} from "./knowledgeCollectionInspectorModel";
import styles from "./NodeKnowledgeCollectionSection.styles";

const KNOWLEDGE_COMMANDS = new Set<CommandOffer["command"]>([
  "ensure_knowledge_collection",
  "inspect_knowledge_collection",
]);

const SIDEFLOW_STATUS_LABELS: Record<string, string> = {
  pending: "待开始",
  running: "进行中",
  waiting_human: "等待交接",
  succeeded: "已完成",
  failed: "失败",
};

type SideflowCard = { nodeId: string; status: keyof typeof SIDEFLOW_STATUS_LABELS };

/** Five-card progress along the fixed sideflow chain, anchored at the
 * server-reported current knowledge node — never a guessed middle node. */
export function sideflowProgressCards(
  currentKnowledgeNodeId: string | null | undefined,
  phase: KnowledgeCollectionInspectorModel["phase"],
): SideflowCard[] {
  const currentIndex = currentKnowledgeNodeId
    ? KNOWLEDGE_SIDEFLOW_NODE_IDS.indexOf(
        currentKnowledgeNodeId as (typeof KNOWLEDGE_SIDEFLOW_NODE_IDS)[number],
      )
    : -1;
  return KNOWLEDGE_SIDEFLOW_NODE_IDS.map((nodeId, position) => {
    let status: SideflowCard["status"] = "pending";
    if (phase === "handed_off" || (currentIndex >= 0 && position < currentIndex)) {
      status = "succeeded";
    } else if (currentIndex >= 0 && position === currentIndex) {
      status =
        phase === "awaiting_handoff"
          ? "waiting_human"
          : phase === "failed"
            ? "failed"
            : "running";
    }
    return { nodeId, status };
  });
}

function offerRequirementLines(payload: Record<string, unknown> | undefined): {
  keywords: string;
  evidenceTypes: string;
  timeWindow: string;
  sourcePolicy: string;
} {
  const envelope = (payload?.searchEnvelope ?? {}) as Record<string, unknown>;
  const requirements = (payload?.requirements ?? {}) as Record<string, unknown>;
  const join = (value: unknown) =>
    Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean).join("、") : "";
  return {
    keywords: join(envelope.keywords) || "—",
    evidenceTypes: join(requirements.evidenceTypes) || "—",
    timeWindow: requirements.timeWindow ? String(requirements.timeWindow) : "—",
    sourcePolicy: requirements.sourcePolicy ? String(requirements.sourcePolicy) : "—",
  };
}

export type NodeKnowledgeCollectionSectionProps = {
  badge: KnowledgeInvocationBadge | null | undefined;
  offers: CommandOffer[];
  /** When set, only offers targeting this node (or node-agnostic offers) are
   * actionable; ksf_ selections omit it to surface the run-level offers. */
  nodeId?: string | null;
  busy: boolean;
  onOffer: (offer: CommandOffer) => Promise<void>;
  lang?: "zh" | "en";
};

export function NodeKnowledgeCollectionSection(props: NodeKnowledgeCollectionSectionProps) {
  const isZh = props.lang !== "en";
  const model = buildKnowledgeCollectionInspectorModel({ badge: props.badge });
  const knowledgeOffers = props.offers.filter(
    (offer) => KNOWLEDGE_COMMANDS.has(offer.command)
      && (props.nodeId == null || offer.nodeId == null || offer.nodeId === props.nodeId),
  );
  const requirements = offerRequirementLines(knowledgeOffers[0]?.payload);
  const phaseChipTone: "neutral" | "info" | "warning" | "danger" | "success" =
    model.phase === "failed"
      ? "danger"
      : model.phase === "awaiting_handoff"
        ? "warning"
        : model.phase === "handed_off"
          ? "success"
          : model.phase === "collecting"
            ? "info"
            : "neutral";

  return (
    <section className={styles.root} data-vui="node-knowledge-collection">
      <div className={styles.head}>
        <h4 className={styles.title}>{isZh ? "补充知识" : "Knowledge"}</h4>
        <VChip tone={phaseChipTone}>{model.headline}</VChip>
      </div>
      {model.detail ? <p className={styles.detail}>{model.detail}</p> : null}

      {model.phase === "not_started" ? (
        <dl className={styles.preview} data-testid="knowledge-collection-preview">
          <dt className={styles.label}>{isZh ? "关键词" : "Keywords"}</dt>
          <dd className={styles.value}>{requirements.keywords}</dd>
          <dt className={styles.label}>{isZh ? "证据类型" : "Evidence"}</dt>
          <dd className={styles.value}>{requirements.evidenceTypes}</dd>
          <dt className={styles.label}>{isZh ? "时间窗" : "Window"}</dt>
          <dd className={styles.value}>{requirements.timeWindow}</dd>
          <dt className={styles.label}>{isZh ? "来源策略" : "Policy"}</dt>
          <dd className={styles.value}>{requirements.sourcePolicy}</dd>
        </dl>
      ) : null}

      {model.progress ? (
        <ol className={styles.cards} data-testid="knowledge-sideflow-progress">
          {sideflowProgressCards(model.lineage.currentKnowledgeNodeId, model.phase).map((card) => (
            <li key={card.nodeId} className={styles.card} data-sideflow-status={card.status}>
              {card.nodeId} · {SIDEFLOW_STATUS_LABELS[card.status]}
            </li>
          ))}
        </ol>
      ) : null}

      {model.packageRef ? (
        <p className={styles.packageLine}>
          {isZh ? "知识包" : "Package"}: <code>{model.packageRef}</code>
          {model.packageHash ? ` · ${model.packageHash.slice(0, 12)}` : ""}
        </p>
      ) : null}

      {knowledgeOffers.length > 0 ? (
        <div className={styles.actions}>
          {knowledgeOffers.map((offer) => {
            const gated = isOperatorGatedOffer(offer);
            const disabled = !offer.available || gated || props.busy;
            const gateReason = offer.authorizationReason
              ?? (offer.available ? "operator_permission_required" : offer.reasonCode);
            return (
              <VButton
                key={offer.idempotencyKey}
                type="button"
                variant="secondary"
                density="compact"
                isDisabled={disabled}
                disabledReason={isZh ? `需要 operator 权限：${gateReason}` : `Operator permission required: ${gateReason}`}
                onPress={() => {
                  void props.onOffer(offer).catch(() => undefined);
                }}
              >
                {offer.label}
              </VButton>
            );
          })}
          {knowledgeOffers.some((offer) => isOperatorGatedOffer(offer)) ? (
            <p role="note" className={styles.gateNote} data-testid="knowledge-collection-operator-gate">
              {isZh ? "部分动作需要 operator 权限" : "Some actions require operator permission"}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
