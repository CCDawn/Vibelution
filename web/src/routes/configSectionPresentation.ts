export type ConfigSectionPresentationLanguage = "zh" | "en";

export type ConfigFieldPresentationCopy = {
  label: string;
  hint?: string;
};

export type ProgressiveConfigSectionPresentation = {
  sectionTitle: string;
  commonPaths: readonly string[];
  commonTitle: string;
  commonHint: string;
  advancedTitle: string;
  advancedHint: string;
  advancedCountLabel: (count: number) => string;
};

const PET_COMMON_PATHS = [
  "pet.enabled",
  "pet.name",
  "pet.auto_save",
  "pet.save_interval",
] as const;

const CONTEXT_COMPRESSION_COMMON_PATHS = [
  "context_compression.enabled",
  "context_compression.max_token_limit",
  "context_compression.keep_recent_steps",
  "context_compression.summary_max_chars",
  "context_compression.compression_model",
] as const;

const SECTION_PRESENTATION: Record<
  ConfigSectionPresentationLanguage,
  Record<string, ProgressiveConfigSectionPresentation>
> = {
  zh: {
    pet: {
      sectionTitle: "陪伴体",
      commonPaths: PET_COMMON_PATHS,
      commonTitle: "常用设置",
      commonHint: "开启陪伴体、设置名称与自动保存即可开始使用。",
      advancedTitle: "高级设置",
      advancedHint: "心跳、梦境、性格、健康等行为参数通常保持默认即可。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    "context-compression": {
      sectionTitle: "上下文压缩",
      commonPaths: CONTEXT_COMPRESSION_COMMON_PATHS,
      commonTitle: "常用设置",
      commonHint: "先确认是否启用、触发上限、保留步骤和压缩模型。",
      advancedTitle: "高级设置",
      advancedHint: "压缩级别、摘要长度和内容保留策略通常无需频繁调整。",
      advancedCountLabel: (count) => `${count} 项`,
    },
  },
  en: {
    pet: {
      sectionTitle: "Companion",
      commonPaths: PET_COMMON_PATHS,
      commonTitle: "Common settings",
      commonHint: "Enable the companion, choose its name, and confirm automatic saving.",
      advancedTitle: "Advanced settings",
      advancedHint: "Heartbeat, dream, personality, and health behavior usually work with their defaults.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    "context-compression": {
      sectionTitle: "Context compression",
      commonPaths: CONTEXT_COMPRESSION_COMMON_PATHS,
      commonTitle: "Common settings",
      commonHint: "Start with the switch, token limit, recent steps, summary size, and model.",
      advancedTitle: "Advanced settings",
      advancedHint: "Compression levels, summary lengths, and preservation policy rarely need adjustment.",
      advancedCountLabel: (count) => `${count} fields`,
    },
  },
};

const ZH_FIELD_COPY: Record<string, ConfigFieldPresentationCopy> = {
  "pet.enabled": { label: "启用陪伴体", hint: "关闭后会暂停陪伴体相关的状态更新。" },
  "pet.name": { label: "陪伴体名称", hint: "显示在陪伴体空间和相关状态中的名称。" },
  "pet.auto_save": { label: "自动保存状态", hint: "定期保存陪伴体的长期状态。" },
  "pet.save_interval": { label: "自动保存间隔（秒）", hint: "自动保存开启时，两次保存之间的间隔。" },
  "pet.gene": { label: "基础能力", hint: "控制陪伴体如何继承模型能力与上下文规模。" },
  "pet.gene.inherit_from_model": { label: "继承模型能力", hint: "按当前模型能力初始化陪伴体的基础参数。" },
  "pet.gene.context_window_factor": { label: "上下文窗口系数", hint: "按比例调整陪伴体可使用的上下文窗口。" },
  "pet.heart": { label: "心跳与活跃检测", hint: "控制陪伴体在活跃和空闲状态下的心跳更新。" },
  "pet.heart.enabled": { label: "启用心跳", hint: "持续记录陪伴体是否处于活跃状态。" },
  "pet.heart.active_rate": { label: "活跃心跳频率", hint: "陪伴体活跃时写入心跳的频率。" },
  "pet.heart.idle_rate": { label: "空闲心跳频率", hint: "陪伴体空闲时写入心跳的频率。" },
  "pet.heart.cooldown_time": { label: "心跳冷却时间", hint: "连续心跳更新之间的最短等待时间。" },
  "pet.dream": { label: "梦境与记忆整理", hint: "控制陪伴体在空闲期整理和保留记忆。" },
  "pet.dream.enabled": { label: "启用梦境", hint: "允许陪伴体在合适时机进入记忆整理循环。" },
  "pet.dream.compression_triggers_dream": { label: "压缩后触发梦境", hint: "上下文压缩完成后自动启动一次记忆整理。" },
  "pet.dream.dream_duration": { label: "梦境持续时间", hint: "单次梦境整理允许持续的时间。" },
  "pet.dream.keep_key_memory_ratio": { label: "关键记忆保留比例", hint: "梦境整理时保留关键记忆的比例。" },
  "pet.personality": { label: "性格学习", hint: "控制陪伴体从长期互动中学习性格特征。" },
  "pet.personality.enabled": { label: "启用性格学习", hint: "允许陪伴体根据长期互动调整性格特征。" },
  "pet.personality.learning_window": { label: "学习窗口", hint: "用于性格学习的最近互动范围。" },
  "pet.personality.trait_change_rate": { label: "性格变化速率", hint: "限制单次学习对性格特征的调整幅度。" },
  "pet.hunger": { label: "饱食与情绪", hint: "控制饱食度、心情衰减和自动喂食。" },
  "pet.hunger.enabled": { label: "启用饱食系统", hint: "让陪伴体随时间产生饱食度变化。" },
  "pet.hunger.food_per_meal": { label: "每次进食补充量", hint: "一次喂食恢复的饱食度。" },
  "pet.hunger.hunger_decay_rate": { label: "饱食度衰减速率", hint: "饱食度随时间下降的速度。" },
  "pet.hunger.mood_decay_rate": { label: "心情衰减速率", hint: "心情随时间下降的速度。" },
  "pet.hunger.auto_feed_threshold": { label: "自动喂食阈值", hint: "饱食度低于该值时触发自动喂食。" },
  "pet.diary": { label: "陪伴日记", hint: "控制长期互动日记的记录、总结与情绪分析。" },
  "pet.diary.enabled": { label: "启用陪伴日记", hint: "记录陪伴体的重要长期互动。" },
  "pet.diary.max_entries": { label: "最大日记条目数", hint: "日记中最多保留的条目数量。" },
  "pet.diary.auto_summarize": { label: "自动总结日记", hint: "日记增长后自动生成简要总结。" },
  "pet.diary.sentiment_analysis": { label: "分析日记情绪", hint: "为日记条目补充情绪倾向。" },
  "pet.social": { label: "社交关系", hint: "控制陪伴体对其他模型和长期关系的记录。" },
  "pet.social.enabled": { label: "启用社交关系", hint: "允许陪伴体维护长期关系状态。" },
  "pet.social.track_other_models": { label: "记录其他模型", hint: "将互动过的其他模型加入关系记录。" },
  "pet.social.friendship_gain_rate": { label: "亲密度增长速率", hint: "控制互动带来的亲密度增长幅度。" },
  "pet.social.max_friends": { label: "最大好友数", hint: "关系记录中最多保留的好友数量。" },
  "pet.health": { label: "健康评估", hint: "根据响应时间、错误率和效率评估陪伴体状态。" },
  "pet.health.enabled": { label: "启用健康评估", hint: "定期计算陪伴体的健康状态。" },
  "pet.health.check_interval": { label: "检查间隔", hint: "两次健康评估之间的等待时间。" },
  "pet.health.response_time_weight": { label: "响应时间权重", hint: "响应速度在健康评分中的占比。" },
  "pet.health.error_rate_weight": { label: "错误率权重", hint: "错误率在健康评分中的占比。" },
  "pet.health.efficiency_weight": { label: "效率权重", hint: "运行效率在健康评分中的占比。" },
  "pet.skin": { label: "外观解锁", hint: "控制陪伴体外观和成就解锁方式。" },
  "pet.skin.enabled": { label: "启用外观", hint: "允许陪伴体使用可解锁外观。" },
  "pet.skin.unlock_by_achievement": { label: "按成就解锁", hint: "完成成就后解锁新的陪伴体外观。" },
  "pet.sound": { label: "声音反馈", hint: "控制陪伴体的音量、心情音效和操作音效。" },
  "pet.sound.enabled": { label: "启用声音", hint: "允许陪伴体播放声音反馈。" },
  "pet.sound.volume": { label: "音量", hint: "陪伴体声音反馈的全局音量。" },
  "pet.sound.mood_sounds": { label: "心情音效", hint: "根据陪伴体心情播放对应音效。" },
  "pet.sound.action_sounds": { label: "操作音效", hint: "在关键互动和状态变化时播放音效。" },
  "context_compression.enabled": { label: "启用上下文压缩", hint: "上下文接近上限时自动压缩较早内容。" },
  "context_compression.max_token_limit": { label: "触发压缩的 Token 上限", hint: "上下文达到该 Token 数量后开始考虑压缩。" },
  "context_compression.keep_recent_steps": { label: "保留最近步骤数", hint: "压缩后仍然保留的最近步骤数。" },
  "context_compression.summary_max_chars": { label: "单次摘要最大字符数", hint: "限制一次压缩摘要可生成的最大字符数。" },
  "context_compression.compression_model": { label: "压缩使用的模型", hint: "用于生成上下文摘要的模型标识。" },
  "context_compression.compression_temperature": { label: "压缩随机性", hint: "越低越稳定，通常保持默认值即可。" },
  "context_compression.max_compressions_per_session": { label: "每会话最大压缩次数", hint: "单会话允许的最大压缩次数。" },
  "context_compression.effectiveness_threshold": { label: "压缩有效性阈值", hint: "压缩收益低于该阈值时不继续压缩。" },
  "context_compression.levels": { label: "压缩级别阈值", hint: "按上下文占用程度选择轻度、标准、深度或紧急压缩。" },
  "context_compression.levels.light": { label: "轻度压缩阈值", hint: "达到该占用比例后可使用轻度压缩。" },
  "context_compression.levels.standard": { label: "标准压缩阈值", hint: "达到该占用比例后可使用标准压缩。" },
  "context_compression.levels.deep": { label: "深度压缩阈值", hint: "达到该占用比例后可使用深度压缩。" },
  "context_compression.levels.emergency": { label: "紧急压缩阈值", hint: "接近容量极限时使用紧急压缩。" },
  "context_compression.summary_chars": { label: "各级摘要长度", hint: "分别限制不同压缩级别生成的摘要长度。" },
  "context_compression.summary_chars.light": { label: "轻度摘要字符数", hint: "轻度压缩生成的目标摘要长度。" },
  "context_compression.summary_chars.standard": { label: "标准摘要字符数", hint: "标准压缩生成的目标摘要长度。" },
  "context_compression.summary_chars.deep": { label: "深度摘要字符数", hint: "深度压缩生成的目标摘要长度。" },
  "context_compression.summary_chars.emergency": { label: "紧急摘要字符数", hint: "紧急压缩生成的目标摘要长度。" },
  "context_compression.preservation": { label: "内容保留策略", hint: "指定压缩时必须保留的消息与关键信息。" },
  "context_compression.preservation.keep_ai_messages": { label: "保留 AI 消息数", hint: "压缩后仍完整保留的最近 AI 消息数量。" },
  "context_compression.preservation.keep_tool_results": { label: "保留工具结果", hint: "压缩时保留工具调用结果。" },
  "context_compression.preservation.preserve_errors": { label: "保留错误信息", hint: "压缩时保留错误与失败上下文。" },
  "context_compression.preservation.extract_key_decisions": { label: "提取关键决策", hint: "把重要决策提取到压缩摘要中。" },
};

const EN_FIELD_COPY: Record<string, ConfigFieldPresentationCopy> = {
  "pet.enabled": { label: "Enable companion" },
  "pet.name": { label: "Companion name" },
  "pet.auto_save": { label: "Save automatically" },
  "pet.save_interval": { label: "Save interval" },
  "context_compression.enabled": { label: "Enable context compression" },
  "context_compression.max_token_limit": { label: "Compression token limit" },
  "context_compression.keep_recent_steps": { label: "Recent steps to keep" },
  "context_compression.summary_max_chars": { label: "Maximum summary length" },
  "context_compression.compression_model": { label: "Compression model" },
};

export function configSectionPresentation(
  sectionId: string,
  language: ConfigSectionPresentationLanguage,
): ProgressiveConfigSectionPresentation | null {
  return SECTION_PRESENTATION[language][sectionId] ?? null;
}

export function isCommonConfigSectionEntry(sectionId: string, absolutePath: string): boolean {
  const presentation = SECTION_PRESENTATION.zh[sectionId];
  return presentation ? presentation.commonPaths.includes(absolutePath) : true;
}

export function configSectionTierCounts(sectionId: string, fieldCount: number): { common: number; advanced: number } {
  const presentation = SECTION_PRESENTATION.zh[sectionId];
  if (!presentation) {
    return { common: fieldCount, advanced: 0 };
  }
  const common = Math.min(fieldCount, presentation.commonPaths.length);
  return { common, advanced: Math.max(0, fieldCount - common) };
}

export function configSectionFieldCopy(
  path: string,
  language: ConfigSectionPresentationLanguage,
): ConfigFieldPresentationCopy | null {
  return (language === "zh" ? ZH_FIELD_COPY[path] : EN_FIELD_COPY[path]) ?? null;
}
