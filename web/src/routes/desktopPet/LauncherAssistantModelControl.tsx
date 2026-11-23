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
export /** Cross-provider quick views stay hidden on short catalogues. */
const QUICK_VIEW_MIN_CHOICES = 8;
const RECENT_MODELS_STORAGE_KEY = "vibelution.launcherAssistant.recentModels";
const RECENT_MODELS_LIMIT = 5;
const USABLE_GROUP_KEY = "__usable__";
const RECENT_GROUP_KEY = "__recent__";

function readRecentModelIds(): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(RECENT_MODELS_STORAGE_KEY) || "[]");
    return Array.isArray(parsed)
      ? parsed.filter(item => typeof item === "string").slice(0, RECENT_MODELS_LIMIT)
      : [];
  } catch {
    return [];
  }
}

function rememberModelId(modelId: string): string[] {
  const next = [modelId, ...readRecentModelIds().filter(item => item !== modelId)]
    .slice(0, RECENT_MODELS_LIMIT);
  try {
    window.localStorage.setItem(RECENT_MODELS_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Private mode keeps only the in-memory order for this menu.
  }
  return next;
}

function launcherAssistantModelDisabledReason(
  choice: LauncherAssistantModelChoice,
  lang: "zh" | "en",
): string {
  if (choice.providerEnabled === false) {
    return lang === "zh" ? "此服务未启用，请在模型设置中开启" : "This provider is disabled; enable it in model settings";
  }
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
  recentModelIds: readonly string[] = [],
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
  if (!normalizedQuery && choices.length >= QUICK_VIEW_MIN_CHOICES) {
    const usable = choices.filter(choice => !launcherAssistantModelDisabledReason(choice, lang));
    if (usable.length) {
      groups.set(USABLE_GROUP_KEY, {
        groupKey: USABLE_GROUP_KEY,
        groupLabel: lang === "zh" ? "可用模型" : "Available models",
        items: usable.map(choice => ({
          key: choice.modelId,
          label: (choice.label || choice.modelId).trim() || choice.modelId,
          title: choice.modelId,
        })),
      });
    }
    const recent = recentModelIds
      .map(id => choices.find(choice => choice.modelId === id))
      .filter((choice): choice is LauncherAssistantModelChoice => Boolean(choice));
    if (recent.length) {
      groups.set(RECENT_GROUP_KEY, {
        groupKey: RECENT_GROUP_KEY,
        groupLabel: lang === "zh" ? "最近使用" : "Recently used",
        items: recent.map(choice => ({
          key: choice.modelId,
          label: (choice.label || choice.modelId).trim() || choice.modelId,
          title: choice.modelId,
          reason: launcherAssistantModelDisabledReason(choice, lang) || undefined,
        })),
      });
    }
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
  const [recentModelIds, setRecentModelIds] = useState<string[]>(readRecentModelIds);
  const zh = lang === "zh";
  const label = choices.find(choice => choice.modelId === modelId)?.label || modelDisplay;
  const locked = pending || selectionDisabled;
  const groups = useMemo(
    () => launcherAssistantModelGroups(choices, lang, query, modelId, modelDisplay, recentModelIds),
    [choices, lang, modelDisplay, modelId, query, recentModelIds],
  );
  const currentProviderLabel = (choices.find(choice => choice.modelId === modelId)?.providerLabel || "").trim();
  const defaultExpandedGroupKeys = [
    ...(choices.some(choice => choice.modelId === modelId) ? [] : ["__current__"]),
    ...(choices.length >= QUICK_VIEW_MIN_CHOICES ? [RECENT_GROUP_KEY, USABLE_GROUP_KEY] : []),
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
        onSelect={(nextModelId) => {
          setRecentModelIds(rememberModelId(nextModelId));
          onModelChange(nextModelId);
          setOpen(false);
          setQuery("");
        }}
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