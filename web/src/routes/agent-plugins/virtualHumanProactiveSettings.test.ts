import { describe, expect, it } from "vitest";

import type { AgentPluginBinding } from "../../api/types";
import {
  DEFAULT_VIRTUAL_HUMAN_PROACTIVE_DAILY_LIMIT,
  DEFAULT_VIRTUAL_HUMAN_PROACTIVE_MINIMUM_INTERVAL_MINUTES,
  mergeVirtualHumanBindingConfig,
  virtualHumanProactivePreset,
  virtualHumanProactivePresetId,
} from "./virtualHumanProactiveSettings";

describe("virtual-human proactive settings", () => {
  it("uses the approved higher natural default", () => {
    expect(DEFAULT_VIRTUAL_HUMAN_PROACTIVE_DAILY_LIMIT).toBe(10);
    expect(DEFAULT_VIRTUAL_HUMAN_PROACTIVE_MINIMUM_INTERVAL_MINUTES).toBe(60);
    expect(virtualHumanProactivePreset("natural")).toEqual({
      id: "natural",
      dailyLimit: 10,
      minimumIntervalMinutes: 60,
    });
    expect(virtualHumanProactivePreset("active")?.dailyLimit).toBe(16);
  });

  it("recognizes presets and keeps unmatched values customizable", () => {
    expect(virtualHumanProactivePresetId(4, 240)).toBe("quiet");
    expect(virtualHumanProactivePresetId(10, 60)).toBe("natural");
    expect(virtualHumanProactivePresetId(16, 45)).toBe("active");
    expect(virtualHumanProactivePresetId(12, 75)).toBe("custom");
  });

  it("preserves unrelated binding fields while applying a quick-settings patch", () => {
    const binding: AgentPluginBinding = {
      agentId: "agent-1",
      pluginId: "virtual-human-life",
      enabled: true,
      configVersion: 3,
      bindingRevision: 4,
      timezone: "Europe/Paris",
      nightlyPlanningTime: "21:45",
      heartbeatIntervalSeconds: 90,
      autonomyLevel: "assisted",
      proactiveMessagesEnabled: true,
      proactiveDailyLimit: 2,
      proactiveMinimumIntervalMinutes: 180,
      quietHours: { start: "00:30", end: "07:45" },
      rhythmConfig: { chronotype: "late" },
    };

    expect(mergeVirtualHumanBindingConfig(binding, {
      proactiveDailyLimit: 16,
      proactiveMinimumIntervalMinutes: 45,
    })).toEqual({
      timezone: "Europe/Paris",
      nightlyPlanningTime: "21:45",
      heartbeatIntervalSeconds: 90,
      autonomyLevel: "assisted",
      proactiveMessagesEnabled: true,
      proactiveDailyLimit: 16,
      proactiveMinimumIntervalMinutes: 45,
      quietHours: { start: "00:30", end: "07:45" },
      rhythmConfig: { chronotype: "late" },
    });
  });
});
