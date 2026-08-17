import { ChevronDown, MessageSquare, Settings2, Users } from "lucide-react";
import { useMemo, useState } from "react";

import type { AgentModelChoice } from "../../../api/types";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import {
  VButton,
  VConfirmDialog,
  VIconButton,
  VNativeButton,
  VNativeInput,
  VPopover,
  VRouteLinkButton,
  VStatusChip,
  VTooltip,
  type VStatusTone,
} from "../../../components/vui";
import {
  agentModelChoiceDisabledReason,
  groupAgentModelCandidates,
} from "../../AgentModelPicker";
import "./NodeInspectorOpsCard.css";
import { nodeInspectorOpsCardStyles as styles } from "./NodeInspectorOpsCard.styles";
import {
  providerVisualId,
  type NodeInspectorBudgetMeter,
  type NodeInspectorProviderVisual,
} from "./nodeInspectorOpsModel";

export type NodeInspectorAgentOption = {
  id: string;
  name: string;
  initial: string;
};

export type NodeInspectorOpsCardProps = {
  stageLabel: string;
  title: string;
  status: { tone: VStatusTone; label: string };
  unbound: boolean;
  agentId: string;
  agentName: string;
  agentInitial: string;
  modelLabel: string;
  modelMeta: string;
  providerVisual: NodeInspectorProviderVisual;
  selectedModelRef: string;
  candidates: AgentModelChoice[];
  pendingModelRef: string;
  modelPending: boolean;
  meters: NodeInspectorBudgetMeter[];
  primaryOffer: CommandOffer | null;
  busy: boolean;
  onOffer?: (offer: CommandOffer) => Promise<void>;
  sessionHref: string | null;
  sessionDisabledReason?: string;
  configHref: string | null;
  agents: NodeInspectorAgentOption[];
  agentSwitchDisabled: boolean;
  agentSwitchReason?: string;
  onSelectAgent?: (agentId: string) => void;
  onSelectPinned: (modelRef: string) => void;
  onPromote: (candidate: AgentModelChoice) => void;
  notice?: string | null;
};

function BudgetMeter(props: NodeInspectorBudgetMeter) {
  return (
    <VTooltip content={props.detail}>
      <div className={`${styles.meter} ${props.warn ? styles.meterWarn : ""}`}>
        <div className={styles.meterHead}>
          <span>{props.label}</span>
          <span>{props.percent}%</span>
        </div>
        <div className={styles.meterTrack} aria-hidden="true">
          <div
            className={styles.meterFill}
            style={{ ["--nio-fill" as string]: `${props.percent <= 0 ? 0 : Math.max(4, Math.min(100, props.percent))}%` }}
          />
        </div>
      </div>
    </VTooltip>
  );
}

export function NodeInspectorOpsCard(props: NodeInspectorOpsCardProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [pendingPromote, setPendingPromote] = useState<AgentModelChoice | null>(null);
  const modelDisabled = props.unbound || props.modelPending;
  const groups = useMemo(
    () => groupAgentModelCandidates(props.candidates, "dialogue", query),
    [props.candidates, query],
  );

  function chooseModel(candidate: AgentModelChoice) {
    const reason = agentModelChoiceDisabledReason(candidate, "dialogue", false);
    if (modelDisabled || reason) return;
    if (candidate.runtimeSelectable) {
      props.onSelectPinned(candidate.modelRef);
      setPickerOpen(false);
      setQuery("");
      return;
    }
    setPendingPromote(candidate);
    setPickerOpen(false);
    setQuery("");
  }

  return (
    <section data-vui="node-inspector-ops-card">
      <header className={styles.header}>
        <div className={styles.stage}>{props.stageLabel}</div>
        <div className={styles.titleRow}>
          <h3 className={styles.title}>{props.title}</h3>
          <VStatusChip tone={props.status.tone}>{props.status.label}</VStatusChip>
        </div>
      </header>

      <div className={styles.identity}>
        <span className={props.unbound ? styles.avatarEmpty : styles.avatar} aria-hidden="true">
          {props.unbound ? "?" : props.agentInitial}
        </span>
        <div className={styles.identityCopy}>
          <strong className={styles.name}>{props.unbound ? "未指定 Agent" : props.agentName}</strong>
        </div>
        {props.agentSwitchDisabled || !props.agents.length ? (
          <VIconButton
            label="更换 Agent"
            icon={<Users size={15} />}
            variant="ghost"
            isDisabled
            disabledReason={props.agentSwitchReason || "暂无可更换 Agent"}
          />
        ) : (
          <VPopover
            open={agentOpen}
            onOpenChange={setAgentOpen}
            align="end"
            contentClassName={styles.picker}
            trigger={(
              <VButton
                type="button"
                variant="ghost"
                isIconOnly
                aria-label="更换 Agent"
                icon={<Users size={15} />}
              />
            )}
          >
            <div className={styles.pickerList} role="listbox" aria-label="更换 Agent">
              {props.agents.map((agent) => {
                const active = agent.id === props.agentId && !props.unbound;
                return (
                  <VNativeButton
                    key={agent.id}
                    className={`${styles.pickerAgentItem} ${active ? styles.pickerItemActive : ""}`}
                    aria-selected={active}
                    onClick={() => {
                      props.onSelectAgent?.(agent.id);
                      setAgentOpen(false);
                    }}
                  >
                    <span className={styles.pickerAvatar} aria-hidden="true">{agent.initial}</span>
                    <span className={styles.pickerItemCopy}>
                      <strong className={styles.modelName}>{agent.name}</strong>
                    </span>
                  </VNativeButton>
                );
              })}
            </div>
          </VPopover>
        )}
      </div>

      <VPopover
        open={pickerOpen}
        onOpenChange={(open) => {
          setPickerOpen(open);
          if (!open) setQuery("");
        }}
        align="start"
        contentClassName={styles.picker}
        trigger={(
          <VNativeButton
            className={styles.modelTrigger}
            data-provider={props.providerVisual}
            data-empty={props.unbound ? "true" : "false"}
            data-testid="node-inspector-model-trigger"
            disabled={modelDisabled}
            aria-label={props.unbound ? "先指定 Agent 再换模型" : `当前模型 ${props.modelLabel}`}
          >
            <span className={styles.modelRail} aria-hidden="true" />
            <span className={styles.modelBody}>
              <span className={styles.modelKicker}>模型</span>
              <span className={styles.modelName}>{props.unbound ? "—" : props.modelLabel}</span>
              <span className={styles.modelMeta}>{props.modelMeta}</span>
            </span>
            <ChevronDown size={16} aria-hidden="true" />
          </VNativeButton>
        )}
      >
        <div className={styles.pickerSearch}>
          <VNativeInput
            aria-label="搜索模型"
            placeholder="搜索模型"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className={styles.pickerList} role="listbox" aria-label="模型">
          {groups.flatMap((group) => group.items).map((candidate) => {
            const active = candidate.modelRef === props.selectedModelRef;
            const reason = agentModelChoiceDisabledReason(candidate, "dialogue", false);
            const pending = candidate.modelRef === props.pendingModelRef;
            return (
              <VNativeButton
                key={candidate.modelRef}
                className={`${styles.pickerItem} ${active ? styles.pickerItemActive : ""}`}
                data-provider={providerVisualId(candidate.providerId)}
                aria-selected={active}
                disabled={Boolean(reason) || pending}
                title={reason || candidate.modelRef}
                onClick={() => chooseModel(candidate)}
              >
                <span className={styles.modelRail} aria-hidden="true" />
                <span className={styles.pickerItemCopy}>
                  <strong className={styles.modelName}>{candidate.label || candidate.modelRef}</strong>
                  <span className={styles.modelMeta}>
                    {pending
                      ? "处理中…"
                      : `${candidate.providerLabel || candidate.providerId}${reason ? ` · ${reason}` : ""}`}
                  </span>
                </span>
              </VNativeButton>
            );
          })}
        </div>
      </VPopover>

      <section className={styles.budget} aria-label="节点预算">
        {props.meters.map((meter) => (
          <BudgetMeter
            key={meter.key}
            label={meter.label}
            percent={meter.percent}
            detail={meter.detail}
            warn={meter.warn}
          />
        ))}
      </section>

      <div className={styles.actions}>
        {props.primaryOffer ? (
          <VButton
            type="button"
            variant="primary"
            isDisabled={props.busy || !props.primaryOffer.available}
            disabledReason={
              props.primaryOffer.available
                ? undefined
                : (props.primaryOffer.reasonCode || props.primaryOffer.blockerIds[0] || "command_unavailable")
            }
            aria-label={
              props.primaryOffer.available
                ? undefined
                : `${props.primaryOffer.label}：${props.primaryOffer.reasonCode || props.primaryOffer.blockerIds[0] || "command_unavailable"}`
            }
            onClick={() => {
              if (!props.primaryOffer || !props.onOffer) return;
              void props.onOffer(props.primaryOffer).catch(() => undefined);
            }}
          >
            {props.primaryOffer.label}
          </VButton>
        ) : null}
        {props.sessionHref ? (
          <VRouteLinkButton
            to={props.sessionHref}
            variant="ghost"
            aria-label="打开会话"
            className={styles.iconLink}
            icon={<MessageSquare size={15} />}
          />
        ) : (
          <VIconButton
            label="打开会话"
            icon={<MessageSquare size={15} />}
            variant="ghost"
            isDisabled
            disabledReason={props.sessionDisabledReason || "尚未绑定精确会话"}
          />
        )}
        {props.configHref ? (
          <VRouteLinkButton
            to={props.configHref}
            variant="ghost"
            aria-label="源配置"
            className={styles.iconLink}
            icon={<Settings2 size={15} />}
          />
        ) : (
          <VIconButton
            label="源配置"
            icon={<Settings2 size={15} />}
            variant="ghost"
            isDisabled
            disabledReason="先指定 Agent"
          />
        )}
      </div>
      {props.notice ? <p className={styles.notice} role="alert">{props.notice}</p> : null}

      <VConfirmDialog
        open={Boolean(pendingPromote)}
        onOpenChange={(open) => {
          if (!open) setPendingPromote(null);
        }}
        title="固定后使用模型"
        description="此操作将修改 operator config，并只更新当前 Agent 的对话模型。"
        tone="neutral"
        confirmLabel="固定并绑定"
        cancelLabel="取消"
        confirmPending={Boolean(
          pendingPromote && props.pendingModelRef && pendingPromote.modelRef === props.pendingModelRef,
        )}
        onConfirm={() => {
          if (pendingPromote) props.onPromote(pendingPromote);
          setPendingPromote(null);
        }}
      />
    </section>
  );
}
