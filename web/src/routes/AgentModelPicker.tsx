import { Check, ChevronDown, ChevronRight } from "lucide-react";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import type { AgentLlmSlotDefinition, AgentModelChoice } from "../api/types";
import { VButton, VConfirmDialog, VContextualHint, VDialog, VNativeInput, VStateSurface } from "../components/vui";
import styles from "./AgentModelPicker.styles";

export type AgentModelCandidateGroup = {
  providerId: string;
  providerLabel: string;
  items: AgentModelChoice[];
};

export function expandedAgentModelProviderIds(
  groups: AgentModelCandidateGroup[],
  query: string,
  manuallyExpandedProviderIds: ReadonlySet<string>,
  searchCollapsedProviderIds: ReadonlySet<string>,
): Set<string> {
  const searching = Boolean(query.trim());
  return new Set(
    groups
      .filter((group) => searching
        ? !searchCollapsedProviderIds.has(group.providerId)
        : manuallyExpandedProviderIds.has(group.providerId))
      .map((group) => group.providerId),
  );
}

type AgentModelPickerProps = {
  candidates: AgentModelChoice[];
  slot: AgentLlmSlotDefinition;
  selectedModelRef: string;
  disabled: boolean;
  pendingModelRef: string;
  configDraftDirty: boolean;
  agentDraftDirty: boolean;
  onSelectPinned: (modelRef: string) => void;
  onPromote: (candidate: AgentModelChoice) => void;
};

const UNAVAILABLE_STATES = new Set([
  "missing",
  "missing_remote",
  "stale",
  "unavailable",
  "unknown",
]);

function normalizedSearchText(candidate: AgentModelChoice) {
  return [
    candidate.providerId,
    candidate.providerLabel,
    candidate.label,
    candidate.modelRef,
    candidate.upstreamId,
  ].join(" ").toLocaleLowerCase();
}

export function groupAgentModelCandidates(
  candidates: AgentModelChoice[],
  _slot: string,
  query: string,
): AgentModelCandidateGroup[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const groups = new Map<string, AgentModelCandidateGroup>();
  for (const candidate of candidates) {
    if (normalizedQuery && !normalizedSearchText(candidate).includes(normalizedQuery)) {
      continue;
    }
    const providerId = String(candidate.providerId || "unknown").trim() || "unknown";
    const group = groups.get(providerId) ?? {
      providerId,
      providerLabel: String(candidate.providerLabel || providerId).trim() || providerId,
      items: [],
    };
    group.items.push(candidate);
    groups.set(providerId, group);
  }
  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      items: [...group.items].sort((left, right) =>
        (left.label || left.modelRef).localeCompare(right.label || right.modelRef)
        || left.modelRef.localeCompare(right.modelRef)),
    }))
    .sort((left, right) =>
      left.providerLabel.localeCompare(right.providerLabel)
      || left.providerId.localeCompare(right.providerId));
}

function slotCompatibility(candidate: AgentModelChoice, slot: string) {
  return candidate.slotCompatibility?.[slot] ?? {
    allowed: false,
    reasonCode: "slot_compatibility_unknown",
  };
}

function slotReasonLabel(reasonCode: string) {
  if (reasonCode === "non_dialogue_model") return "该模型不是对话模型，不能用于此槽位";
  if (reasonCode === "image_input_unverified") return "图像输入能力尚未验证";
  if (reasonCode === "image_input_unsupported") return "模型不支持图像输入";
  return "模型与当前 Agent 槽位不兼容";
}

function hardDisabledReason(candidate: AgentModelChoice, slot: string) {
  const compatibility = slotCompatibility(candidate, slot);
  if (!compatibility.allowed) {
    return slotReasonLabel(compatibility.reasonCode);
  }
  if (candidate.catalogStale || candidate.verificationStatus === "stale") {
    return "模型发现信息已过期，请先刷新模型发现";
  }
  if (UNAVAILABLE_STATES.has(String(candidate.availability || "").toLowerCase())) {
    return "上游模型当前不可用";
  }
  if (candidate.missingApiKey) {
    return "Provider 尚未配置 API Key";
  }
  return "";
}

/** Pure disable reason for list rows — exported for unit contracts. */
export function agentModelChoiceDisabledReason(
  candidate: AgentModelChoice,
  slot: string,
  draftsDirty: boolean,
): string {
  const hardReason = hardDisabledReason(candidate, slot);
  if (hardReason) return hardReason;
  if (!candidate.runtimeSelectable && draftsDirty) {
    return "请先保存或放弃未保存修改";
  }
  return "";
}

function candidateStatus(candidate: AgentModelChoice) {
  if (candidate.catalogStale || candidate.verificationStatus === "stale") return "已过期";
  if (candidate.source === "both") return "已固定 · 已发现";
  if (candidate.source === "pinned") return "已固定";
  if (candidate.verificationStatus === "verified") return "已发现 · 已验证";
  return "已发现 · 未验证";
}

export function AgentModelPicker({
  candidates,
  slot,
  selectedModelRef,
  disabled,
  pendingModelRef,
  configDraftDirty,
  agentDraftDirty,
  onSelectPinned,
  onPromote,
}: AgentModelPickerProps) {
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const optionRefs = useRef(new Map<string, HTMLButtonElement>());
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeModelRef, setActiveModelRef] = useState("");
  const [manuallyExpandedProviderIds, setManuallyExpandedProviderIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [searchCollapsedProviderIds, setSearchCollapsedProviderIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [pendingPromote, setPendingPromote] = useState<AgentModelChoice | null>(null);
  const groups = useMemo(
    () => groupAgentModelCandidates(candidates, slot.slot, query),
    [candidates, query, slot.slot],
  );
  const expandedProviderIds = useMemo(
    () => expandedAgentModelProviderIds(
      groups,
      query,
      manuallyExpandedProviderIds,
      searchCollapsedProviderIds,
    ),
    [groups, manuallyExpandedProviderIds, query, searchCollapsedProviderIds],
  );
  const visibleCandidates = useMemo(
    () => groups
      .filter((group) => expandedProviderIds.has(group.providerId))
      .flatMap((group) => group.items),
    [expandedProviderIds, groups],
  );
  const selected = candidates.find((candidate) => candidate.modelRef === selectedModelRef);
  const draftsDirty = configDraftDirty || agentDraftDirty;

  function disabledReason(candidate: AgentModelChoice) {
    return agentModelChoiceDisabledReason(candidate, slot.slot, draftsDirty);
  }

  const enabledCandidates = useMemo(
    () => visibleCandidates.filter((candidate) => !agentModelChoiceDisabledReason(
      candidate,
      slot.slot,
      draftsDirty,
    )),
    [draftsDirty, slot.slot, visibleCandidates],
  );

  useEffect(() => {
    if (!open) return;
    const first = enabledCandidates[0]?.modelRef ?? "";
    setActiveModelRef((current) => enabledCandidates.some((item) => item.modelRef === current) ? current : first);
  }, [enabledCandidates, open]);

  useEffect(() => {
    if (!open) return;
    requestAnimationFrame(() => searchRef.current?.focus());
  }, [open]);

  useEffect(() => {
    setSearchCollapsedProviderIds(new Set());
  }, [query]);

  function restoreTriggerFocus() {
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  function closePicker() {
    setOpen(false);
    setQuery("");
    setManuallyExpandedProviderIds(new Set());
    setSearchCollapsedProviderIds(new Set());
    setActiveModelRef("");
    restoreTriggerFocus();
  }

  function openPicker() {
    setQuery("");
    setManuallyExpandedProviderIds(new Set());
    setSearchCollapsedProviderIds(new Set());
    setActiveModelRef("");
    setOpen(true);
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      openPicker();
      return;
    }
    closePicker();
  }

  function choose(candidate: AgentModelChoice) {
    if (disabled || disabledReason(candidate)) return;
    if (candidate.runtimeSelectable) {
      onSelectPinned(candidate.modelRef);
      closePicker();
      return;
    }
    setPendingPromote(candidate);
    setOpen(false);
    setQuery("");
  }

  function closePromoteConfirm() {
    setPendingPromote(null);
    restoreTriggerFocus();
  }

  function moveActive(delta: number) {
    if (!enabledCandidates.length) return;
    const currentIndex = enabledCandidates.findIndex((item) => item.modelRef === activeModelRef);
    const nextIndex = currentIndex < 0
      ? 0
      : (currentIndex + delta + enabledCandidates.length) % enabledCandidates.length;
    const next = enabledCandidates[nextIndex];
    setActiveModelRef(next.modelRef);
    requestAnimationFrame(() => optionRefs.current.get(next.modelRef)?.focus());
  }

  function toggleProvider(providerId: string) {
    const update = (current: Set<string>) => {
      const next = new Set(current);
      if (next.has(providerId)) next.delete(providerId);
      else next.add(providerId);
      return next;
    };
    if (query.trim()) {
      setSearchCollapsedProviderIds(update);
      return;
    }
    setManuallyExpandedProviderIds(update);
  }

  function handlePanelKeyDown(event: KeyboardEvent) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      const next = event.key === "Home" ? enabledCandidates[0] : enabledCandidates.at(-1);
      if (next) {
        setActiveModelRef(next.modelRef);
        requestAnimationFrame(() => optionRefs.current.get(next.modelRef)?.focus());
      }
    }
  }

  const dialogTitle = `选择 ${slot.label}`;

  return (
    <>
      <div className={styles.root}>
        <VButton
          ref={triggerRef}
          type="button"
          contentLayout="plain"
          className={styles.trigger}
          isDisabled={disabled}
          aria-haspopup="dialog"
          aria-expanded={open}
          onPress={openPicker}
        >
          <span className={styles.triggerCopy}>
            <span className={styles.triggerLabel}>
              {selected?.label || selectedModelRef || "选择模型"}
            </span>
            <span className={styles.triggerMeta}>{selected?.providerLabel || ""}</span>
          </span>
          <ChevronDown size={14} aria-hidden="true" />
        </VButton>
        <VDialog
          open={open}
          onOpenChange={handleOpenChange}
          title={(
            <span className={styles.contextualHintRow}>
              <span>{dialogTitle}</span>
              <VContextualHint
                label="模型选择说明"
                content="按 Provider 分组。可直接搜索模型名 / gpt / luna。已固定的点「使用」；未固定的点「固定后使用」会先加入模型库再绑定。"
                width="wide"
              />
            </span>
          )}
          description="按 Provider 分组浏览；搜索支持模型名、Provider 与 modelRef。"
          size="xl"
          contentClassName={styles.dialogContent}
          aria-label={dialogTitle}
        >
          <div className={styles.dialogBody} onKeyDown={handlePanelKeyDown}>
            <VNativeInput
              ref={searchRef}
              className={styles.search}
              value={query}
              aria-label="搜索模型"
              placeholder="快速过滤：模型名 / gpt-5 / luna / Provider"
              onChange={(event) => setQuery(event.target.value)}
            />
            <div className={styles.list} aria-label={`${slot.label}模型候选`}>
              {groups.map((group, groupIndex) => {
                const groupExpanded = expandedProviderIds.has(group.providerId);
                const groupPanelId = `agent-model-provider-${groupIndex}-${group.providerId.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
                return (
                  <section key={group.providerId} className={styles.group} aria-label={group.providerLabel}>
                    <VButton
                      type="button"
                      contentLayout="plain"
                      className={styles.groupHeader}
                      aria-expanded={groupExpanded}
                      aria-controls={groupPanelId}
                      onPress={() => toggleProvider(group.providerId)}
                    >
                      <span className={styles.groupTitle}>
                        {groupExpanded
                          ? <ChevronDown className={styles.groupChevron} size={14} aria-hidden="true" />
                          : <ChevronRight className={styles.groupChevron} size={14} aria-hidden="true" />}
                        <span>{group.providerLabel}</span>
                      </span>
                      <span className={styles.groupCount}>{group.items.length} 个模型</span>
                    </VButton>
                    <div
                      id={groupPanelId}
                      className={styles.groupItems}
                      role="listbox"
                      aria-label={`${group.providerLabel} ${slot.label}模型`}
                      hidden={!groupExpanded}
                    >
                    {group.items.map((candidate) => {
                    const reason = disabledReason(candidate);
                    const compatibility = slotCompatibility(candidate, slot.slot);
                    const selectedRow = candidate.modelRef === selectedModelRef;
                    const pending = candidate.modelRef === pendingModelRef;
                    return (
                      <VButton
                        key={candidate.modelRef}
                        ref={(node) => {
                          if (node) optionRefs.current.set(candidate.modelRef, node);
                          else optionRefs.current.delete(candidate.modelRef);
                        }}
                        type="button"
                        contentLayout="plain"
                        role="option"
                        className={`${styles.option} ${selectedRow ? styles.optionSelected : ""} ${reason ? styles.optionDisabled : ""}`}
                        isDisabled={disabled || Boolean(reason)}
                        aria-selected={selectedRow}
                        data-reason-code={compatibility.reasonCode || undefined}
                        title={candidate.modelRef}
                        onFocus={() => setActiveModelRef(candidate.modelRef)}
                        onPress={() => choose(candidate)}
                      >
                        <span className={styles.optionCopy}>
                          <span className={styles.optionTitle}>
                            <span>{candidate.label || candidate.upstreamId}</span>
                            <span className={styles.badge}>{candidateStatus(candidate)}</span>
                            {selectedRow ? <Check className={styles.check} size={14} aria-hidden="true" /> : null}
                          </span>
                          <span className={styles.optionMeta}>
                            {candidate.reasoningEffortValues?.length
                              ? <span>{candidate.reasoningEffortValues.join(" / ")}</span>
                              : <span>标准推理</span>}
                            <span>{candidate.transport || candidate.providerKind}</span>
                          </span>
                        </span>
                        <span className={styles.action}>
                          {pending ? "处理中…" : candidate.runtimeSelectable ? "使用" : "固定后使用"}
                        </span>
                        {reason ? <span className={styles.reason}>{reason}</span> : null}
                      </VButton>
                    );
                    })}
                    </div>
                  </section>
                );
              })}
              {!groups.length ? <VStateSurface tone="empty" title="没有匹配的模型" /> : null}
            </div>
          </div>
        </VDialog>
      </div>
      <VConfirmDialog
        open={Boolean(pendingPromote)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            closePromoteConfirm();
          }
        }}
        title="固定后使用模型"
        description="此操作将修改 operator config，并只更新当前 Agent 的模型绑定。"
        tone="neutral"
        confirmLabel="固定并绑定"
        cancelLabel="取消"
        confirmPending={Boolean(
          pendingPromote && pendingModelRef && pendingPromote.modelRef === pendingModelRef,
        )}
        onConfirm={() => {
          if (pendingPromote) {
            onPromote(pendingPromote);
          }
          closePromoteConfirm();
        }}
      >
        {pendingPromote ? (
          <div className={styles.promoteFacts}>
            <div className={styles.promoteFact}>
              <strong className={styles.promoteFactLabel}>Provider：</strong>
              {pendingPromote.providerLabel || pendingPromote.providerId}
            </div>
            <div className={styles.promoteFact}>
              <strong className={styles.promoteFactLabel}>upstream ID：</strong>
              {pendingPromote.upstreamId}
            </div>
            <div className={styles.promoteFact}>
              <strong className={styles.promoteFactLabel}>modelRef：</strong>
              {pendingPromote.modelRef}
            </div>
          </div>
        ) : null}
      </VConfirmDialog>
    </>
  );
}
