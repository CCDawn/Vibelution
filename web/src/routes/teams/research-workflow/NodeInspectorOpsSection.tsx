import type { ResearchBudgetProjection, EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import { NodeInspectorOpsCard } from "./NodeInspectorOpsCard";
import {
  agentDisplayInitial,
  ledgerForStage,
  nodeInspectorBudgetMeters,
  nodeInspectorStatus,
  providerVisualId,
  researchAgentConfigRoute,
} from "./nodeInspectorOpsModel";
import { inspectorAgentOptions, useNodeInspectorOpsResources } from "./useNodeInspectorOpsResources";

export type NodeInspectorOpsSectionProps = {
  teamId: string;
  nodeId: string;
  stageId: string;
  stageLabel: string;
  title: string;
  agentId: string;
  agentName: string;
  unbound: boolean;
  runtimeCurrent?: boolean;
  status?: string | null;
  canRebindAgent: boolean;
  agentSwitchReason?: string;
  effectiveBindings: EffectiveAgentBinding[] | null;
  budget: ResearchBudgetProjection | null;
  primaryOffer: CommandOffer | null;
  busy: boolean;
  onOffer?: (offer: CommandOffer) => Promise<void>;
  sessionHref: string | null;
  sessionDisabledReason?: string;
};

export function NodeInspectorOpsSection(props: NodeInspectorOpsSectionProps) {
  const resources = useNodeInspectorOpsResources(props.agentId);
  const meters = nodeInspectorBudgetMeters(ledgerForStage(props.budget?.budgetLedgers, props.stageId));
  const status = nodeInspectorStatus({
    unbound: props.unbound,
    runtimeCurrent: Boolean(props.runtimeCurrent),
    status: props.status,
    budgetWarn: meters.some((meter) => meter.warn),
  });
  const model = resources.dialogueModel;
  const modelLabel = model?.label
    || model?.modelRef
    || resources.agent?.llmBindings?.dialogue?.modelId
    || (resources.modelPending ? "…" : "—");
  const modelMeta = props.unbound
    ? "指定 Agent 后可切换"
    : model
      ? (model.providerLabel || model.providerId)
      : "未配置模型";

  return (
    <NodeInspectorOpsCard
      stageLabel={props.stageLabel}
      title={props.title}
      status={status}
      unbound={props.unbound}
      agentId={props.agentId}
      agentName={props.agentName}
      agentInitial={agentDisplayInitial(props.agentName)}
      modelLabel={modelLabel}
      modelMeta={modelMeta}
      providerVisual={providerVisualId(model?.providerId || "")}
      selectedModelRef={model?.modelRef || resources.agent?.llmBindings?.dialogue?.modelId || ""}
      candidates={resources.candidates}
      pendingModelRef={resources.pendingModelRef}
      modelPending={resources.modelPending}
      meters={meters}
      primaryOffer={props.primaryOffer}
      busy={props.busy}
      onOffer={props.onOffer}
      sessionHref={props.sessionHref}
      sessionDisabledReason={props.sessionDisabledReason}
      configHref={researchAgentConfigRoute(props.agentId)}
      agents={inspectorAgentOptions(resources.workspace?.agents)}
      agentSwitchDisabled={!props.canRebindAgent}
      agentSwitchReason={props.agentSwitchReason}
      onSelectAgent={(agentId) => {
        if (!props.canRebindAgent) return;
        resources.bindAgent({
          teamId: props.teamId,
          nodeId: props.nodeId,
          agentId,
          bindings: props.effectiveBindings,
        });
      }}
      onSelectPinned={resources.selectPinned}
      onPromote={resources.promote}
      notice={resources.notice}
    />
  );
}
