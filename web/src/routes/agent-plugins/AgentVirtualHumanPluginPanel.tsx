import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HeartPulse, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { listAgentPlugins, updateAgentPluginBinding } from "../../api/agentPlugins";
import { queryKeys } from "../../api/queryKeys";
import type { AgentPluginBinding } from "../../api/types";
import {
  VButton,
  VCheckbox,
  VInput,
  VSelect,
  VStateSurface,
  VStatusChip,
} from "../../components/vui";
import styles from "./AgentVirtualHumanPluginPanel.styles";

const PLUGIN_ID = "virtual-human-life";

type BindingDraft = {
  autonomyLevel: "assisted" | "autonomous";
  proactiveMessagesEnabled: boolean;
  nightlyPlanningTime: string;
  proactiveDailyLimit: number;
  proactiveMinimumIntervalMinutes: number;
  quietStart: string;
  quietEnd: string;
};

const DEFAULT_DRAFT: BindingDraft = {
  autonomyLevel: "autonomous",
  proactiveMessagesEnabled: true,
  nightlyPlanningTime: "22:30",
  proactiveDailyLimit: 2,
  proactiveMinimumIntervalMinutes: 180,
  quietStart: "23:00",
  quietEnd: "08:00",
};

function draftFromBinding(binding: AgentPluginBinding | null | undefined): BindingDraft {
  return {
    autonomyLevel: binding?.autonomyLevel === "assisted" ? "assisted" : "autonomous",
    proactiveMessagesEnabled: binding?.proactiveMessagesEnabled ?? true,
    nightlyPlanningTime: binding?.nightlyPlanningTime || DEFAULT_DRAFT.nightlyPlanningTime,
    proactiveDailyLimit: binding?.proactiveDailyLimit ?? DEFAULT_DRAFT.proactiveDailyLimit,
    proactiveMinimumIntervalMinutes: binding?.proactiveMinimumIntervalMinutes ?? DEFAULT_DRAFT.proactiveMinimumIntervalMinutes,
    quietStart: binding?.quietHours?.start || DEFAULT_DRAFT.quietStart,
    quietEnd: binding?.quietHours?.end || DEFAULT_DRAFT.quietEnd,
  };
}

function bindingConfig(draft: BindingDraft): Record<string, unknown> {
  return {
    autonomyLevel: draft.autonomyLevel,
    proactiveMessagesEnabled: draft.proactiveMessagesEnabled,
    nightlyPlanningTime: draft.nightlyPlanningTime,
    proactiveDailyLimit: draft.proactiveDailyLimit,
    proactiveMinimumIntervalMinutes: draft.proactiveMinimumIntervalMinutes,
    quietHours: { start: draft.quietStart, end: draft.quietEnd },
  };
}

export function AgentVirtualHumanPluginPanel({ agentId, lang }: { agentId: string; lang: "zh" | "en" }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<BindingDraft>(DEFAULT_DRAFT);
  const [feedback, setFeedback] = useState("");
  const pluginsQuery = useQuery({
    queryKey: queryKeys.agentPlugins(agentId),
    queryFn: () => listAgentPlugins(agentId),
    enabled: Boolean(agentId),
  });
  const plugin = useMemo(
    () => pluginsQuery.data?.plugins.find((item) => item.pluginId === PLUGIN_ID) ?? null,
    [pluginsQuery.data],
  );
  const binding = plugin?.binding ?? null;
  const bindingSignature = JSON.stringify(binding ?? {});

  useEffect(() => {
    setDraft(draftFromBinding(binding));
    setFeedback("");
  }, [agentId, bindingSignature]);

  const bindingMutation = useMutation({
    mutationFn: ({ enabled, nextDraft }: { enabled: boolean; nextDraft: BindingDraft }) => (
      updateAgentPluginBinding(agentId, PLUGIN_ID, {
        enabled,
        expectedVersion: binding?.configVersion ?? 0,
        config: bindingConfig(nextDraft),
      })
    ),
    onSuccess: async (nextBinding) => {
      queryClient.setQueryData(queryKeys.agentPlugins(agentId), (current: typeof pluginsQuery.data) => {
        if (!current) return current;
        return {
          ...current,
          plugins: current.plugins.map((item) => (
            item.pluginId === PLUGIN_ID ? { ...item, binding: nextBinding } : item
          )),
        };
      });
      setDraft(draftFromBinding(nextBinding));
      setFeedback(lang === "zh" ? "虚拟人生活配置已更新。" : "Virtual-human life settings updated.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanCompanions() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.virtualHumanSnapshot(agentId) }),
      ]);
    },
    onError: (error) => {
      setFeedback(error instanceof Error ? error.message : (lang === "zh" ? "更新失败" : "Update failed"));
    },
  });
  const pending = bindingMutation.isPending;
  const enabled = Boolean(binding?.enabled);

  if (pluginsQuery.isPending) {
    return <VStateSurface className={styles.state} title={lang === "zh" ? "正在载入虚拟人插件" : "Loading virtual-human plugin"} tone="loading" density="compact" />;
  }
  if (pluginsQuery.isError || !plugin) {
    return (
      <VStateSurface className={styles.state} title={lang === "zh" ? "虚拟人插件不可用" : "Virtual-human plugin unavailable"} tone="error" density="compact">
        {pluginsQuery.error instanceof Error ? pluginsQuery.error.message : "virtual-human-life"}
      </VStateSurface>
    );
  }

  return (
    <section className={styles.panel} aria-label={lang === "zh" ? "虚拟人生活插件" : "Virtual Human Life plugin"}>
      <div className={styles.header}>
        <div className={styles.title}>
          <HeartPulse size={17} aria-hidden="true" />
          <div className={styles.titleCopy}>
            <p>{lang === "zh" ? "Agent 插件" : "Agent plugin"}</p>
            <h3>{plugin.displayName}</h3>
          </div>
        </div>
        <VStatusChip tone={enabled ? "success" : "neutral"}>
          {enabled ? (lang === "zh" ? "已启用" : "Enabled") : (lang === "zh" ? "未启用" : "Disabled")}
        </VStatusChip>
      </div>

      <p className={styles.description}>
        {lang === "zh"
          ? "只为当前 Agent 增加独立生活、心情、次日日程和受控主动消息；不会改变其他 Agent。"
          : "Adds an independent life, moods, next-day plans, and controlled proactive messages to this Agent only."}
      </p>
      <div className={styles.badges}>
        <span className={styles.badge}>Tool bundle · {plugin.toolBundleId}</span>
        <span className={styles.badge}>Prompt pack · {plugin.promptPackId}</span>
        <span className={styles.badge}>{plugin.toolNames.length} {lang === "zh" ? "个专属工具" : "plugin tools"}</span>
      </div>

      {enabled ? (
        <div className={styles.grid}>
          <label className={styles.field}>
            <span>{lang === "zh" ? "自主等级" : "Autonomy"}</span>
            <VSelect
              aria-label={lang === "zh" ? "自主等级" : "Autonomy"}
              selectedKey={draft.autonomyLevel}
              isDisabled={pending}
              options={[
                { id: "autonomous", label: lang === "zh" ? "Autonomous（推荐）" : "Autonomous (recommended)" },
                { id: "assisted", label: lang === "zh" ? "Assisted" : "Assisted" },
              ]}
              onSelectionChange={(value) => setDraft((current) => ({
                ...current,
                autonomyLevel: value === "assisted" ? "assisted" : "autonomous",
              }))}
            />
          </label>
          <label className={styles.field}>
            <span>{lang === "zh" ? "次日规划时间" : "Next-day planning time"}</span>
            <VInput
              type="time"
              value={draft.nightlyPlanningTime}
              disabled={pending}
              onChange={(event) => setDraft((current) => ({ ...current, nightlyPlanningTime: event.target.value }))}
            />
          </label>
          <label className={styles.field}>
            <span>{lang === "zh" ? "每日主动消息上限" : "Daily proactive limit"}</span>
            <VInput
              type="number"
              min={0}
              max={20}
              value={draft.proactiveDailyLimit}
              disabled={pending}
              onChange={(event) => setDraft((current) => ({ ...current, proactiveDailyLimit: Number(event.target.value) }))}
            />
          </label>
          <label className={styles.field}>
            <span>{lang === "zh" ? "主动消息最小间隔（分钟）" : "Minimum proactive interval (minutes)"}</span>
            <VInput
              type="number"
              min={1}
              max={1440}
              value={draft.proactiveMinimumIntervalMinutes}
              disabled={pending}
              onChange={(event) => setDraft((current) => ({ ...current, proactiveMinimumIntervalMinutes: Number(event.target.value) }))}
            />
          </label>
          <div className={styles.fieldWide}>
            <span>{lang === "zh" ? "免打扰时间" : "Quiet hours"}</span>
            <span className={styles.quietHours}>
              <VInput type="time" value={draft.quietStart} disabled={pending} aria-label={lang === "zh" ? "免打扰开始" : "Quiet start"} onChange={(event) => setDraft((current) => ({ ...current, quietStart: event.target.value }))} />
              <VInput type="time" value={draft.quietEnd} disabled={pending} aria-label={lang === "zh" ? "免打扰结束" : "Quiet end"} onChange={(event) => setDraft((current) => ({ ...current, quietEnd: event.target.value }))} />
            </span>
          </div>
          <div className={styles.fieldWide}>
            <VCheckbox
              isSelected={draft.proactiveMessagesEnabled}
              isDisabled={pending}
              onChange={(selected) => setDraft((current) => ({ ...current, proactiveMessagesEnabled: selected }))}
            >
              {lang === "zh" ? "允许在额度、间隔和免打扰范围内主动联系" : "Allow proactive messages within limits and quiet hours"}
            </VCheckbox>
          </div>
        </div>
      ) : null}

      {feedback ? <p className={styles.notice} role="status">{feedback}</p> : null}
      <div className={styles.actions}>
        {enabled ? (
          <VButton
            type="button"
            variant="primary"
            icon={<Save size={14} />}
            isPending={pending}
            onPress={() => bindingMutation.mutate({ enabled: true, nextDraft: draft })}
          >
            {lang === "zh" ? "保存插件配置" : "Save plugin settings"}
          </VButton>
        ) : null}
        <VButton
          type="button"
          variant={enabled ? "danger" : "primary"}
          isPending={pending}
          onPress={() => bindingMutation.mutate({ enabled: !enabled, nextDraft: draft })}
        >
          {enabled ? (lang === "zh" ? "禁用插件" : "Disable plugin") : (lang === "zh" ? "启用虚拟人生活" : "Enable Virtual Human Life")}
        </VButton>
      </div>
    </section>
  );
}
