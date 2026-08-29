import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellRing, Check, ChevronDown } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { updateAgentPluginBinding } from "../../api/agentPlugins";
import { queryKeys } from "../../api/queryKeys";
import type { VirtualHumanCompanion } from "../../api/types";
import { VButton, VCheckbox, VPopover } from "../../components/vui";
import {
  mergeVirtualHumanBindingConfig,
  VIRTUAL_HUMAN_PROACTIVE_PRESETS,
  virtualHumanProactivePresetId,
  type VirtualHumanProactivePreset,
} from "../agent-plugins/virtualHumanProactiveSettings";
import styles from "./CompanionProactiveSettingsPopover.styles";

const PLUGIN_ID = "virtual-human-life";

const PRESET_COPY = {
  zh: {
    quiet: ["安静", "每天最多 4 次 · 至少间隔 4 小时"],
    natural: ["自然", "每天最多 10 次 · 至少间隔 1 小时"],
    active: ["活跃", "每天最多 16 次 · 至少间隔 45 分钟"],
    custom: "自定义",
  },
  en: {
    quiet: ["Quiet", "Up to 4 per day · at least 4 hours apart"],
    natural: ["Natural", "Up to 10 per day · at least 1 hour apart"],
    active: ["Active", "Up to 16 per day · at least 45 minutes apart"],
    custom: "Custom",
  },
} as const;

type CompanionProactiveSettingsPopoverProps = {
  companion: VirtualHumanCompanion;
  lang: "zh" | "en";
};

export function CompanionProactiveSettingsPopover({
  companion,
  lang,
}: CompanionProactiveSettingsPopoverProps) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  const binding = companion.snapshot.binding;
  const enabled = binding?.proactiveMessagesEnabled ?? true;
  const currentPresetId = virtualHumanProactivePresetId(
    binding?.proactiveDailyLimit ?? 10,
    binding?.proactiveMinimumIntervalMinutes ?? 60,
  );
  const currentLabel = currentPresetId === "custom"
    ? PRESET_COPY[lang].custom
    : PRESET_COPY[lang][currentPresetId][0];
  const usage = companion.snapshot.proactiveUsage;

  useEffect(() => {
    setOpen(false);
    setFeedback("");
  }, [companion.agentId]);

  const mutation = useMutation({
    mutationFn: async (patch: Record<string, unknown>) => {
      if (!binding) {
        throw new Error(lang === "zh" ? "虚拟人插件尚未绑定。" : "The virtual-human plugin is not bound yet.");
      }
      return updateAgentPluginBinding(companion.agentId, PLUGIN_ID, {
        enabled: binding.enabled,
        expectedVersion: binding.configVersion,
        config: mergeVirtualHumanBindingConfig(binding, patch),
      });
    },
    onSuccess: async (nextBinding) => {
      queryClient.setQueryData<VirtualHumanCompanion[]>(
        queryKeys.virtualHumanCompanions(),
        (current) => current?.map((item) => (
          item.agentId === companion.agentId
            ? {
              ...item,
              snapshot: {
                ...item.snapshot,
                binding: nextBinding,
                proactiveUsage: {
                  ...item.snapshot.proactiveUsage,
                  limit: nextBinding.proactiveDailyLimit ?? item.snapshot.proactiveUsage.limit,
                  remaining: Math.max(
                    0,
                    (nextBinding.proactiveDailyLimit ?? item.snapshot.proactiveUsage.limit)
                      - item.snapshot.proactiveUsage.delivered,
                  ),
                },
              },
            }
            : item
        )),
      );
      setFeedback(lang === "zh" ? "主动联系设置已更新。" : "Proactive contact settings updated.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanCompanions() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanSnapshot(companion.agentId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.agentPlugins(companion.agentId) }),
      ]);
    },
    onError: (error) => {
      setFeedback(error instanceof Error ? error.message : (lang === "zh" ? "更新失败" : "Update failed"));
    },
  });

  const presetRows = useMemo(() => VIRTUAL_HUMAN_PROACTIVE_PRESETS.map((preset) => ({
    preset,
    copy: PRESET_COPY[lang][preset.id],
  })), [lang]);

  const applyPreset = (preset: VirtualHumanProactivePreset) => {
    mutation.mutate({
      proactiveMessagesEnabled: true,
      proactiveDailyLimit: preset.dailyLimit,
      proactiveMinimumIntervalMinutes: preset.minimumIntervalMinutes,
    });
  };

  return (
    <div className={styles.root} data-companion-proactive-settings="true">
      <VPopover
        open={open}
        onOpenChange={setOpen}
        side="bottom"
        align="end"
        sideOffset={6}
        aria-label={lang === "zh" ? "主动联系设置" : "Proactive contact settings"}
        contentClassName={styles.panel}
        data-vui="companion-proactive-settings"
        trigger={(
          <VButton
            type="button"
            variant="ghost"
            className={styles.trigger}
            icon={<BellRing size={14} aria-hidden="true" />}
            trailingIcon={<ChevronDown size={12} aria-hidden="true" />}
            aria-haspopup="dialog"
            aria-expanded={open}
          >
            <span>{lang === "zh" ? "主动联系" : "Proactive"}</span>
            <span aria-hidden="true">·</span>
            <span className={styles.triggerState}>{enabled ? currentLabel : (lang === "zh" ? "关闭" : "Off")}</span>
          </VButton>
        )}
      >
        <div className={styles.header}>
          <h2 className={styles.title}>{lang === "zh" ? "主动联系频率" : "Proactive contact frequency"}</h2>
          <p className={styles.description}>
            {lang === "zh"
              ? "只调整当前人物。免打扰时间和完整自定义值仍沿用人物插件配置。"
              : "Only this person is affected. Quiet hours and custom values remain in the Agent plugin settings."}
          </p>
          <p className={styles.usage}>
            {lang === "zh"
              ? `今天已发送 ${usage.delivered} 次，还可发送 ${usage.remaining} 次`
              : `${usage.delivered} sent today · ${usage.remaining} remaining`}
          </p>
        </div>
        <div className={styles.presetList} role="listbox" aria-label={lang === "zh" ? "主动联系频率" : "Proactive contact frequency"}>
          {presetRows.map(({ preset, copy }) => {
            const selected = enabled && currentPresetId === preset.id;
            return (
              <VButton
                key={preset.id}
                type="button"
                contentLayout="plain"
                variant={selected ? "primary" : "secondary"}
                className={styles.presetButton}
                role="option"
                aria-selected={selected}
                isDisabled={mutation.isPending || !binding}
                onPress={() => applyPreset(preset)}
              >
                <span className={styles.presetCopy}>
                  <span className={styles.presetLabel}>{copy[0]}</span>
                  <span className={styles.presetMeta}>{copy[1]}</span>
                </span>
                {selected ? <Check className={styles.presetCheck} size={15} aria-hidden="true" /> : null}
              </VButton>
            );
          })}
        </div>
        <div className={styles.toggle}>
          <VCheckbox
            isSelected={enabled}
            isDisabled={mutation.isPending || !binding}
            onChange={(selected) => mutation.mutate({ proactiveMessagesEnabled: selected })}
          >
            {lang === "zh" ? "允许这个人物主动联系我" : "Allow this person to contact me proactively"}
          </VCheckbox>
        </div>
        {feedback ? <p className={styles.feedback} role="status">{feedback}</p> : null}
      </VPopover>
    </div>
  );
}
