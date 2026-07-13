import { describe, expect, it } from "vitest";

import {
  configSectionFieldCopy,
  configSectionPresentation,
  configSectionTierCounts,
  isCommonConfigSectionEntry,
} from "./configSectionPresentation";

const petPaths = [
  "pet.enabled",
  "pet.name",
  "pet.auto_save",
  "pet.save_interval",
  "pet.gene",
  "pet.gene.inherit_from_model",
  "pet.gene.context_window_factor",
  "pet.heart",
  "pet.heart.enabled",
  "pet.heart.active_rate",
  "pet.heart.idle_rate",
  "pet.heart.cooldown_time",
  "pet.dream",
  "pet.dream.enabled",
  "pet.dream.compression_triggers_dream",
  "pet.dream.dream_duration",
  "pet.dream.keep_key_memory_ratio",
  "pet.personality",
  "pet.personality.enabled",
  "pet.personality.learning_window",
  "pet.personality.trait_change_rate",
  "pet.hunger",
  "pet.hunger.enabled",
  "pet.hunger.food_per_meal",
  "pet.hunger.hunger_decay_rate",
  "pet.hunger.mood_decay_rate",
  "pet.hunger.auto_feed_threshold",
  "pet.diary",
  "pet.diary.enabled",
  "pet.diary.max_entries",
  "pet.diary.auto_summarize",
  "pet.diary.sentiment_analysis",
  "pet.social",
  "pet.social.enabled",
  "pet.social.track_other_models",
  "pet.social.friendship_gain_rate",
  "pet.social.max_friends",
  "pet.health",
  "pet.health.enabled",
  "pet.health.check_interval",
  "pet.health.response_time_weight",
  "pet.health.error_rate_weight",
  "pet.health.efficiency_weight",
  "pet.skin",
  "pet.skin.enabled",
  "pet.skin.unlock_by_achievement",
  "pet.sound",
  "pet.sound.enabled",
  "pet.sound.volume",
  "pet.sound.mood_sounds",
  "pet.sound.action_sounds",
];

const contextCompressionPaths = [
  "context_compression.enabled",
  "context_compression.max_token_limit",
  "context_compression.keep_recent_steps",
  "context_compression.summary_max_chars",
  "context_compression.compression_model",
  "context_compression.compression_temperature",
  "context_compression.max_compressions_per_session",
  "context_compression.effectiveness_threshold",
  "context_compression.levels",
  "context_compression.levels.light",
  "context_compression.levels.standard",
  "context_compression.levels.deep",
  "context_compression.levels.emergency",
  "context_compression.summary_chars",
  "context_compression.summary_chars.light",
  "context_compression.summary_chars.standard",
  "context_compression.summary_chars.deep",
  "context_compression.summary_chars.emergency",
  "context_compression.preservation",
  "context_compression.preservation.keep_ai_messages",
  "context_compression.preservation.keep_tool_results",
  "context_compression.preservation.preserve_errors",
  "context_compression.preservation.extract_key_decisions",
];

describe("progressive config section presentation", () => {
  it("keeps only everyday pet and context controls in the common tier", () => {
    expect(configSectionPresentation("pet", "zh")?.sectionTitle).toBe("陪伴体");
    expect(configSectionPresentation("pet", "zh")?.commonPaths).toEqual([
      "pet.enabled",
      "pet.name",
      "pet.auto_save",
      "pet.save_interval",
    ]);
    expect(configSectionPresentation("context-compression", "zh")?.commonPaths).toEqual([
      "context_compression.enabled",
      "context_compression.max_token_limit",
      "context_compression.keep_recent_steps",
      "context_compression.summary_max_chars",
      "context_compression.compression_model",
    ]);

    expect(isCommonConfigSectionEntry("pet", "pet.name")).toBe(true);
    expect(isCommonConfigSectionEntry("pet", "pet.heart")).toBe(false);
    expect(isCommonConfigSectionEntry("context-compression", "context_compression.compression_model")).toBe(true);
    expect(isCommonConfigSectionEntry("context-compression", "context_compression.levels")).toBe(false);
  });

  it("reports collapsed advanced field counts without changing backend field totals", () => {
    expect(configSectionTierCounts("pet", 41)).toEqual({ common: 4, advanced: 37 });
    expect(configSectionTierCounts("context-compression", 20)).toEqual({ common: 5, advanced: 15 });
    expect(configSectionTierCounts("security", 5)).toEqual({ common: 5, advanced: 0 });
  });

  it("provides Chinese labels for every visible pet and context-compression control", () => {
    for (const path of [...petPaths, ...contextCompressionPaths]) {
      const copy = configSectionFieldCopy(path, "zh");
      expect(copy?.label, path).toMatch(/[\u3400-\u9fff]/);
    }

    expect(configSectionFieldCopy("pet.heart.active_rate", "zh")).toEqual({
      label: "活跃心跳频率",
      hint: "陪伴体活跃时写入心跳的频率。",
    });
    expect(configSectionFieldCopy("context_compression.max_token_limit", "zh")).toEqual({
      label: "触发压缩的 Token 上限",
      hint: "上下文达到该 Token 数量后开始考虑压缩。",
    });
    expect(configSectionFieldCopy("context_compression.levels", "zh")?.label).toBe("压缩级别阈值");
  });

  it("keeps an English presentation and leaves unrelated fields untouched", () => {
    expect(configSectionPresentation("pet", "en")?.advancedTitle).toBe("Advanced settings");
    expect(configSectionFieldCopy("pet.save_interval", "en")?.label).toBe("Save interval");
    expect(configSectionFieldCopy("security.enabled", "zh")).toBeNull();
    expect(configSectionPresentation("security", "zh")).toBeNull();
  });
});
