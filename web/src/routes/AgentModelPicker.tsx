import { ChevronDown } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import type { AgentLlmSlotDefinition, AgentModelChoice } from "../api/types";
import {
  ConversationModelCandidateList,
  expandedModelCandidateGroupKeys,
  type ConversationModelCandidateGroup,
} from "../components/conversation/ConversationModelCandidateList";
import { VButton, VConfirmDialog, VPopover } from "../components/vui";
import styles from "./AgentModelPicker.styles";

export type AgentModelCandidateGroup = {
  providerId: string;
  providerLabel: string;
  items: AgentModelChoice[];
};

/**
 * Compatibility facade over the shared disclosure rule: Agent slots keep their
 * provider-id grouping while the expansion semantics live in exactly one place
 * (ConversationModelCandidateList).
 */
export function expandedAgentModelProviderIds(
  groups: AgentModelCandidateGroup[],
  query: string,
  manuallyExpandedProviderIds: ReadonlySet<string>,
  searchCollapsedProviderIds: ReadonlySet<string>,
): Set<string> {
  return expandedModelCandidateGroupKeys(
    groups.map((group) => ({ groupKey: group.providerId, groupLabel: group.providerLabel, items: [] })),
    query,
    manuallyExpandedProviderIds,
    searchCollapsedProviderIds,
  );
}

type AgentModelPickerProps = {
  lang?: "zh" | "en";
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

/**
 * Provider channel health comes from the backend candidate DTO
 * (`providerHealthy`, same determination as the provider registry rail).
 * Broken channels (auth/discovery/protocol failure or missing key) are hidden
 * from the menu entirely; `undefined` (older payloads) stays usable.
 */
export function hasUsableProviderChannel(candidate: AgentModelChoice): boolean {
  return candidate.providerHealthy !== false;
}

/** Menu candidates only; the selected-model fallback keeps the full list. */
export function filterUsableProviderCandidates(
  candidates: AgentModelChoice[],
): AgentModelChoice[] {
  return candidates.filter(hasUsableProviderChannel);
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
    return "此服务尚未配置 API Key";
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

export function AgentModelPicker({
  lang = "zh",
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
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [pendingPromote, setPendingPromote] = useState<AgentModelChoice | null>(null);
  const menuCandidates = useMemo(
    () => filterUsableProviderCandidates(candidates),
    [candidates],
  );
  const groups = useMemo(
    () => groupAgentModelCandidates(menuCandidates, slot.slot, query),
    [menuCandidates, query, slot.slot],
  );
  const selected = candidates.find((candidate) => candidate.modelRef === selectedModelRef);
  const draftsDirty = configDraftDirty || agentDraftDirty;

  const sharedGroups = useMemo<ConversationModelCandidateGroup[]>(
    () => groups.map((group) => ({
      groupKey: group.providerId,
      groupLabel: group.providerLabel,
      items: group.items.map((candidate) => ({
        key: candidate.modelRef,
        label: candidate.label || candidate.upstreamId,
        title: candidate.modelRef,
        reason: agentModelChoiceDisabledReason(candidate, slot.slot, draftsDirty) || undefined,
        reasonCode: slotCompatibility(candidate, slot.slot).reasonCode || undefined,
        action: candidate.runtimeSelectable ? "" : (lang === "zh" ? "添加" : "Add"),
        pending: candidate.modelRef === pendingModelRef,
      })),
    })),
    [draftsDirty, groups, lang, pendingModelRef, slot.slot],
  );

  const initialExpandedGroupKeys = useMemo(() => {
    const selectedProvider = selected?.providerId;
    const initialProvider = menuCandidates.some((candidate) => candidate.providerId === selectedProvider)
      ? selectedProvider
      : menuCandidates[0]?.providerId;
    return initialProvider ? [initialProvider] : [];
  }, [menuCandidates, selected]);

  function restoreTriggerFocus() {
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  function closePicker() {
    setOpen(false);
    setQuery("");
    restoreTriggerFocus();
  }

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      setOpen(true);
      return;
    }
    closePicker();
  }

  function choose(modelRef: string) {
    const candidate = menuCandidates.find((item) => item.modelRef === modelRef);
    if (!candidate || disabled || agentModelChoiceDisabledReason(candidate, slot.slot, draftsDirty)) {
      return;
    }
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

  const dialogTitle = lang === "zh" ? `选择 ${slot.label}` : `Select ${slot.label}`;

  return (
    <>
      <div className={styles.root}>
        <VPopover
          open={open}
          onOpenChange={handleOpenChange}
          align="end"
          side="bottom"
          sideOffset={8}
          aria-label={dialogTitle}
          contentClassName={styles.dialogContent}
          trigger={(
            <VButton
              ref={triggerRef}
              type="button"
              contentLayout="plain"
              className={styles.trigger}
              isDisabled={disabled}
              aria-haspopup="dialog"
              aria-expanded={open}
              aria-label={dialogTitle}
            >
              <span className={styles.triggerCopy}>
                <span className={styles.triggerLabel}>
                  {selected?.label || selectedModelRef || (slot.required ? (lang === "zh" ? "选择模型" : "Select model") : (lang === "zh" ? "默认" : "Default"))}
                </span>
                <span className={styles.triggerMeta}>{selected?.providerLabel || ""}</span>
              </span>
              <ChevronDown size={14} aria-hidden="true" />
            </VButton>
          )}
        >
          <div className={styles.dialogBody}>
            <ConversationModelCandidateList
              lang={lang}
              groups={sharedGroups}
              selectedKey={selectedModelRef}
              disabled={disabled}
              query={query}
              onQueryChange={setQuery}
              defaultExpandedGroupKeys={initialExpandedGroupKeys}
              leadingOption={!slot.required ? {
                label: lang === "zh" ? "默认" : "Default",
                selected: !selectedModelRef,
                onSelect: () => { onSelectPinned(""); closePicker(); },
              } : undefined}
              listLabel={lang === "zh" ? `${slot.label}模型候选` : `${slot.label} model candidates`}
              onSelect={choose}
            />
          </div>
        </VPopover>
      </div>
      <VConfirmDialog
        open={Boolean(pendingPromote)}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            closePromoteConfirm();
          }
        }}
        title="添加并使用模型"
        description="此操作将修改 模型库配置，并只更新当前 Agent 的模型绑定。"
        tone="neutral"
        confirmLabel="添加并使用"
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