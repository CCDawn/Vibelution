import { SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import type { LauncherAssistantModelChoice } from "../../api/launcherAssistant";
import {
  ConversationModelCandidateList,
  type ConversationModelCandidateGroup,
  type ConversationModelCandidateRow,
} from "../../components/conversation/ConversationModelCandidateList";
import { ConversationModelControlTrigger } from "../../components/conversation/ConversationModelControlTrigger";
import { VButton, VPopover } from "../../components/vui";
import styles from "./LauncherAssistantModelControl.styles";

/** States that mean the upstream model cannot serve a turn right now. */
const UNAVAILABLE_ASSISTANT_MODEL_STATES = new Set([
  "missing",
  "missing_remote",
  "stale",
  "unavailable",
]);

/**
 * Localized reason for an unroutable assistant model, or "" when selectable.
 * The Launcher menu keeps unusable rows visible so an operator learns why a
 * model cannot be picked instead of watching a dead row with no explanation.
 */
export function launcherAssistantModelDisabledReason(
  choice: LauncherAssistantModelChoice,
  lang: "zh" | "en",
): string {
  if (choice.missingApiKey) {
    return lang === "zh" ? "此服务尚未配置 API Key" : "This provider has no API key";
  }
  if (choice.providerHealthy === false) {
    return lang === "zh" ? "该服务通道当前不可用" : "This provider channel is unavailable";
  }
  if (UNAVAILABLE_ASSISTANT_MODEL_STATES.has(String(choice.availability ?? '').trim().toLowerCase())) {
    return lang === "zh" ? "上游模型当前不可用" : "Upstream model is unavailable";
  }
  return "";
}

/** Groups assistant choices by provider label, keeping catalogue order stable. */
export function launcherAssistantModelGroups(
  choices: readonly LauncherAssistantModelChoice[],
  lang: "zh" | "en",
  query: string,
  currentModelId: string,
  currentModelDisplay: string,
): ConversationModelCandidateGroup[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const currentKnown = choices.some((choice) => choice.modelId === currentModelId);
  const groups = new Map<string, ConversationModelCandidateGroup>();
  if (!currentKnown && currentModelId) {
    // The bound model can disappear from the catalogue (provider removed). Keep
    // one honest row for it so the menu never hides what the assistant runs on.
    groups.set("__current__", {
      groupKey: "__current__",
      groupLabel: lang === "zh" ? "当前模型" : "Current model",
      items: [{
        key: currentModelId,
        label: currentModelDisplay || currentModelId,
        title: currentModelId,
        reason: lang === "zh" ? "不在当前可用模型目录中" : "Not in the available model catalogue",
      }],
    });
  }
  for (const choice of choices) {
    const label = (choice.label || choice.modelId).trim() || choice.modelId;
    const providerLabel = (choice.providerLabel || "").trim();
    if (
      normalizedQuery
      && ![label, choice.modelId, providerLabel]
        .some((text) => text.toLocaleLowerCase().includes(normalizedQuery))
    ) {
      continue;
    }
    const groupKey = providerLabel || "__unlabeled__";
    const group = groups.get(groupKey) ?? {
      groupKey,
      groupLabel: providerLabel || (lang === "zh" ? "其他服务" : "Other providers"),
      items: [],
    };
    const row: ConversationModelCandidateRow = {
      key: choice.modelId,
      label,
      title: choice.modelId,
      reason: launcherAssistantModelDisabledReason(choice, lang) || undefined,
    };
    group.items.push(row);
    groups.set(groupKey, group);
  }
  for (const group of groups.values()) {
    // Keep the bound model and usable rows at the top of each provider group.
    // Catalogue order alone pushed the current model below the fold in large
    // groups, so the menu opened on rows the operator could not use yet.
    group.items.sort((left, right) => {
      const selectedDelta = Number(right.key === currentModelId) - Number(left.key === currentModelId);
      if (selectedDelta !== 0) return selectedDelta;
      return Number(Boolean(left.reason)) - Number(Boolean(right.reason));
    });
  }
  return Array.from(groups.values());
}

/** Native Launcher model actions in the shared conversation toolbar recipe. */
export function LauncherAssistantModelControl({
  lang, modelId, modelDisplay, choices = [], pending, selectionDisabled,
  onModelChange, onOpenSettings,
}: {
  lang: "zh" | "en";
  modelId: string;
  modelDisplay: string;
  choices?: LauncherAssistantModelChoice[];
  pending: boolean;
  selectionDisabled: boolean;
  onModelChange: (modelId: string) => void;
  onOpenSettings?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const zh = lang === "zh";
  const label = choices.find(choice => choice.modelId === modelId)?.label || modelDisplay;
  const locked = pending || selectionDisabled;
  const groups = useMemo(
    () => launcherAssistantModelGroups(choices, lang, query, modelId, modelDisplay),
    [choices, lang, modelDisplay, modelId, query],
  );
  const currentProviderLabel = (choices.find(choice => choice.modelId === modelId)?.providerLabel || "").trim();
  const defaultExpandedGroupKeys = [
    ...(choices.some(choice => choice.modelId === modelId) ? [] : ["__current__"]),
    currentProviderLabel || "__unlabeled__",
  ];
  return <div className={styles.root} data-launcher-assistant-model-control>
    <VPopover open={open} onOpenChange={setOpen} side="top" align="end" sideOffset={6}
      aria-label={zh ? "助理模型" : "Assistant model"} contentClassName={styles.popover}
      trigger={<ConversationModelControlTrigger label={label} open={open} isPending={pending}
        aria-label={`${zh ? "助理模型" : "Assistant model"}: ${label}`}
      />}>
      <ConversationModelCandidateList lang={lang} groups={groups} selectedKey={modelId}
        disabled={locked} query={query} onQueryChange={setQuery}
        defaultExpandedGroupKeys={defaultExpandedGroupKeys}
        listLabel={zh ? "助理模型候选" : "Assistant model candidates"}
        searchLabel={zh ? "搜索模型" : "Search models"}
        onSelect={(nextModelId) => { onModelChange(nextModelId); setOpen(false); setQuery(""); }}
      />
      {onOpenSettings ? <div className={styles.actions}>
        <VButton variant="ghost" density="compact" isDisabled={pending}
          icon={<SlidersHorizontal size={12} aria-hidden="true" />}
          onClick={() => { setOpen(false); setQuery(""); onOpenSettings(); }}>
          {zh ? "模型设置" : "Model settings"}
        </VButton>
      </div> : null}
    </VPopover>
  </div>;
}