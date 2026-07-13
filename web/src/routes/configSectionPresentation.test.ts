import { describe, expect, it } from "vitest";

import {
  configSectionExpandedByDefault,
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

const operatorSurfacePaths = [
  "ui.language",
  "ui.theme",
  "ui.max_log_entries",
  "ui.refresh_rate",
  "ui.show_ascii_art",
  "ui.show_welcome",
  "ui.workbench_theme",
  "ui.workbench_theme.background_image_path",
  "ui.workbench_theme.background_readability",
  "security.enabled",
  "security.allowed_directories",
  "security.forbidden_patterns",
  "security.forbidden_delete_patterns",
  "security.dangerous_commands",
  "network.timeout",
  "network.user_agent",
  "network.max_retries",
  "network.retry_delay",
  "network.verify_ssl",
  "network.proxy_enabled",
  "network.proxy_url",
  "parser.strip_tags",
  "parser.strip_thinking_alias",
  "log.level",
  "log.format",
  "log.date_format",
  "log.file_enabled",
  "log.file_path",
  "log.max_file_size",
  "log.backup_count",
  "log.detailed_traceback",
  "log.third_party",
  "log.third_party.httpx",
  "log.third_party.httpcore",
  "log.third_party.langchain",
  "log.third_party.openai",
  "log.third_party.anthropic",
  "log.third_party.urllib3",
  "log.third_party.litellm",
  "log.third_party.rich",
  "debug.enabled",
  "debug.verbose",
  "debug.trace_llm",
  "debug.trace_tools",
  "debug.track_token_usage",
];

describe("progressive config section presentation", () => {
  it("keeps only everyday avatar, pet, and context controls in the common tier", () => {
    expect(configSectionPresentation("avatar", "zh")).toMatchObject({
      sectionTitle: "终端形象",
      sectionSummary: "选择终端、CLI 与陪伴体使用的内置形象；Web 用户头像请在用户资料中设置。",
      layout: "compact_paths",
      commonPaths: ["avatar.preset"],
      commonTitle: "形象预设",
    });
    expect(configSectionPresentation("pet", "zh")).toMatchObject({
      sectionTitle: "陪伴体",
      layout: "compact_paths",
      commonTitle: "快速启用",
      advancedTitle: "行为、记忆与外观（高级）",
    });
    expect(configSectionPresentation("pet", "zh")?.commonPaths).toEqual([
      "pet.enabled",
      "pet.name",
      "pet.auto_save",
    ]);
    expect(configSectionPresentation("context-compression", "zh")?.commonPaths).toEqual([
      "context_compression.enabled",
      "context_compression.max_token_limit",
      "context_compression.keep_recent_steps",
      "context_compression.summary_max_chars",
      "context_compression.compression_model",
    ]);

    expect(isCommonConfigSectionEntry("avatar", "avatar.preset")).toBe(true);
    expect(isCommonConfigSectionEntry("pet", "pet.name")).toBe(true);
    expect(isCommonConfigSectionEntry("pet", "pet.save_interval")).toBe(false);
    expect(isCommonConfigSectionEntry("pet", "pet.heart")).toBe(false);
    expect(isCommonConfigSectionEntry("context-compression", "context_compression.compression_model")).toBe(true);
    expect(isCommonConfigSectionEntry("context-compression", "context_compression.levels")).toBe(false);
  });

  it("reports collapsed advanced field counts without changing backend field totals", () => {
    expect(configSectionTierCounts("avatar", 1)).toEqual({ common: 1, advanced: 0 });
    expect(configSectionTierCounts("pet", 41)).toEqual({ common: 3, advanced: 38 });
    expect(configSectionTierCounts("context-compression", 20)).toEqual({ common: 5, advanced: 15 });
    expect(configSectionTierCounts("analysis", 4)).toEqual({ common: 2, advanced: 2 });
    expect(configSectionTierCounts("user-profile", 5)).toEqual({ common: 3, advanced: 2 });
  });

  it("keeps everyday interface and operator controls in the common tier", () => {
    expect(configSectionPresentation("analysis", "zh")).toMatchObject({
      sectionTitle: "分析数据存储",
      sectionSummary: "设置分析结果、反馈数据和知识资产在工作区中的存放位置。",
      layout: "compact_paths",
      commonPaths: [
        "analysis.data_dir",
        "analysis.feedback_dir",
      ],
      advancedTitle: "知识资产路径",
    });
    expect(configSectionPresentation("ui", "zh")?.commonPaths).toEqual([
      "ui.language",
      "ui.theme",
      "ui.show_ascii_art",
      "ui.show_welcome",
    ]);
    expect(configSectionPresentation("security", "zh")?.commonPaths).toEqual([
      "security.enabled",
    ]);
    expect(configSectionPresentation("network", "zh")?.commonPaths).toEqual([
      "network.timeout",
      "network.proxy_enabled",
      "network.proxy_url",
    ]);
    expect(configSectionPresentation("log", "zh")?.commonPaths).toEqual([
      "log.level",
      "log.file_enabled",
      "log.file_path",
      "log.detailed_traceback",
    ]);
    expect(configSectionPresentation("debug", "zh")?.commonPaths).toEqual([
      "debug.enabled",
      "debug.track_token_usage",
    ]);
    expect(configSectionPresentation("parser", "zh")).toBeNull();

    expect(configSectionPresentation("llm-discovery", "zh")).toMatchObject({
      sectionTitle: "模型发现",
      sectionSummary: "控制工作台如何发现模型，以及无法读取模型限制时使用的回退值。",
      commonPaths: [
        "llm.discovery.enabled",
        "llm.discovery.timeout",
        "llm.discovery.auto_adjust",
      ],
    });

    expect(configSectionTierCounts("ui", 7)).toEqual({ common: 4, advanced: 3 });
    expect(configSectionTierCounts("security", 5)).toEqual({ common: 1, advanced: 4 });
    expect(configSectionTierCounts("network", 7)).toEqual({ common: 3, advanced: 4 });
    expect(configSectionTierCounts("log", 16)).toEqual({ common: 4, advanced: 12 });
    expect(configSectionTierCounts("debug", 5)).toEqual({ common: 2, advanced: 3 });
    expect(configSectionTierCounts("llm-discovery", 6)).toEqual({ common: 3, advanced: 3 });
  });

  it("keeps the Git model visible and the prompt template collapsed by default", () => {
    expect(configSectionPresentation("git-commit-model", "zh")).toMatchObject({
      sectionTitle: "Git 提交助手",
      sectionSummary: "选择生成提交说明时使用的模型；通常只需要配置这一项。",
      layout: "compact_paths",
      commonPaths: ["git.commit_message_model_ref"],
      commonTitle: "模型选择",
    });
    expect(configSectionPresentation("git-commit-prompt", "zh")).toMatchObject({
      sectionTitle: "提示词模板（高级）",
      sectionSummary: "只有默认提交说明格式不满足需要时才修改，并保留 {diff} 占位符。",
      commonPaths: ["git.commit_message_prompt"],
      commonTitle: "模板内容",
    });
    expect(configSectionExpandedByDefault("git-commit-model")).toBe(true);
    expect(configSectionExpandedByDefault("git-commit-prompt")).toBe(false);
    expect(configSectionExpandedByDefault("analysis")).toBe(true);
  });

  it("keeps profile identity visible while treating agent reference text as advanced", () => {
    expect(configSectionPresentation("user-profile", "zh")).toMatchObject({
      sectionTitle: "用户资料与头像",
      sectionSummary: "先设置工作台显示名和头像；只有需要时再补充提供给 Agent 的背景与偏好。",
      commonPaths: [
        "user_profile.display_name",
        "user_profile.avatar_preset",
        "user_profile.avatar_image_path",
      ],
      commonTitle: "基础资料",
      advancedTitle: "Agent 参考信息（高级）",
    });
    expect(isCommonConfigSectionEntry("user-profile", "user_profile.display_name")).toBe(true);
    expect(isCommonConfigSectionEntry("user-profile", "user_profile.avatar_preset")).toBe(true);
    expect(isCommonConfigSectionEntry("user-profile", "user_profile.bio")).toBe(false);
    expect(isCommonConfigSectionEntry("user-profile", "user_profile.preferences")).toBe(false);
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

  it("provides Chinese labels for interface, security, networking, parser, logging, and debug controls", () => {
    for (const path of operatorSurfacePaths) {
      const copy = configSectionFieldCopy(path, "zh");
      expect(copy?.label, path).toMatch(/[\u3400-\u9fff]/);
    }

    expect(configSectionFieldCopy("ui.language", "zh")?.label).toBe("界面语言");
    expect(configSectionFieldCopy("security.dangerous_commands", "zh")?.label).toBe("危险命令拦截规则");
    expect(configSectionFieldCopy("network.proxy_url", "zh")?.label).toBe("代理地址");
    expect(configSectionFieldCopy("log.third_party.openai", "zh")?.label).toBe("OpenAI 日志级别");
    expect(configSectionFieldCopy("debug.track_token_usage", "zh")?.label).toBe("记录 Token 用量");
    expect(configSectionFieldCopy("llm.discovery.enabled", "zh")).toEqual({
      label: "启用自动发现",
      hint: "连接服务商后自动读取可用模型列表。",
    });
    expect(configSectionFieldCopy("llm.discovery.fallback_max_token_limit", "zh")?.label).toBe("默认上下文上限");
    expect(configSectionFieldCopy("analysis.data_dir", "zh")).toEqual({
      label: "分析数据目录",
      hint: "保存分析结果和统计数据的工作区目录。",
    });
    expect(configSectionFieldCopy("analysis.knowledge_graph_path", "zh")?.label).toBe("知识图谱文件");
    expect(configSectionFieldCopy("git.commit_message_prompt", "zh")?.label).toBe("提交说明提示词模板");
  });

  it("keeps an English presentation and leaves unrelated fields untouched", () => {
    expect(configSectionPresentation("pet", "en")?.advancedTitle).toBe("Behavior, memory, and appearance (advanced)");
    expect(configSectionPresentation("llm-discovery", "en")?.commonPaths).toEqual([
      "llm.discovery.enabled",
      "llm.discovery.timeout",
      "llm.discovery.auto_adjust",
    ]);
    expect(configSectionFieldCopy("pet.save_interval", "en")?.label).toBe("Save interval");
    expect(configSectionFieldCopy("llm.discovery.output_reserve_ratio", "en")?.label).toBe("Output reserve ratio");
    expect(configSectionFieldCopy("analysis.pattern_library_path", "en")?.label).toBe("Pattern library file");
    expect(configSectionFieldCopy("git.commit_message_model_ref", "en")?.label).toBe("Commit message model");
    expect(configSectionPresentation("analysis", "en")?.advancedTitle).toBe("Knowledge asset paths");
    expect(configSectionPresentation("user-profile", "en")?.advancedTitle).toBe("Agent reference information (advanced)");
  });
});
