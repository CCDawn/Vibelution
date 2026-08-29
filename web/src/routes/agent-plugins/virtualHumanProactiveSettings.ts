import type { AgentPluginBinding } from "../../api/types";

export const DEFAULT_VIRTUAL_HUMAN_PROACTIVE_DAILY_LIMIT = 10;
export const DEFAULT_VIRTUAL_HUMAN_PROACTIVE_MINIMUM_INTERVAL_MINUTES = 60;

export type VirtualHumanProactivePresetId = "quiet" | "natural" | "active" | "custom";

export type VirtualHumanProactivePreset = {
  id: Exclude<VirtualHumanProactivePresetId, "custom">;
  dailyLimit: number;
  minimumIntervalMinutes: number;
};

export const VIRTUAL_HUMAN_PROACTIVE_PRESETS: readonly VirtualHumanProactivePreset[] = [
  { id: "quiet", dailyLimit: 4, minimumIntervalMinutes: 240 },
  {
    id: "natural",
    dailyLimit: DEFAULT_VIRTUAL_HUMAN_PROACTIVE_DAILY_LIMIT,
    minimumIntervalMinutes: DEFAULT_VIRTUAL_HUMAN_PROACTIVE_MINIMUM_INTERVAL_MINUTES,
  },
  { id: "active", dailyLimit: 16, minimumIntervalMinutes: 45 },
] as const;

export function virtualHumanProactivePresetId(
  dailyLimit: number,
  minimumIntervalMinutes: number,
): VirtualHumanProactivePresetId {
  return VIRTUAL_HUMAN_PROACTIVE_PRESETS.find((preset) => (
    preset.dailyLimit === dailyLimit
    && preset.minimumIntervalMinutes === minimumIntervalMinutes
  ))?.id ?? "custom";
}

export function virtualHumanProactivePreset(
  presetId: VirtualHumanProactivePresetId,
): VirtualHumanProactivePreset | null {
  return VIRTUAL_HUMAN_PROACTIVE_PRESETS.find((preset) => preset.id === presetId) ?? null;
}

export function mergeVirtualHumanBindingConfig(
  binding: AgentPluginBinding | null | undefined,
  patch: Record<string, unknown>,
): Record<string, unknown> {
  return {
    timezone: binding?.timezone || "Asia/Shanghai",
    nightlyPlanningTime: binding?.nightlyPlanningTime || "22:30",
    heartbeatIntervalSeconds: binding?.heartbeatIntervalSeconds ?? 60,
    autonomyLevel: binding?.autonomyLevel === "assisted" ? "assisted" : "autonomous",
    proactiveMessagesEnabled: binding?.proactiveMessagesEnabled ?? true,
    proactiveDailyLimit: binding?.proactiveDailyLimit ?? DEFAULT_VIRTUAL_HUMAN_PROACTIVE_DAILY_LIMIT,
    proactiveMinimumIntervalMinutes:
      binding?.proactiveMinimumIntervalMinutes
      ?? DEFAULT_VIRTUAL_HUMAN_PROACTIVE_MINIMUM_INTERVAL_MINUTES,
    quietHours: {
      start: binding?.quietHours?.start || "23:00",
      end: binding?.quietHours?.end || "08:00",
    },
    rhythmConfig: binding?.rhythmConfig ?? {},
    ...patch,
  };
}
