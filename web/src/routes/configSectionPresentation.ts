export type ConfigSectionPresentationLanguage = "zh" | "en";

export type ConfigFieldPresentationCopy = {
  label: string;
  hint?: string;
};

export type ProgressiveConfigSectionPresentation = {
  sectionTitle: string;
  sectionSummary?: string;
  layout?: "compact_paths";
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

const UI_COMMON_PATHS = [
  "ui.language",
  "ui.theme",
  "ui.show_ascii_art",
  "ui.show_welcome",
] as const;

const SECURITY_COMMON_PATHS = [
  "security.enabled",
] as const;

const NETWORK_COMMON_PATHS = [
  "network.timeout",
  "network.proxy_enabled",
  "network.proxy_url",
] as const;

const LOG_COMMON_PATHS = [
  "log.level",
  "log.file_enabled",
  "log.file_path",
  "log.detailed_traceback",
] as const;

const DEBUG_COMMON_PATHS = [
  "debug.enabled",
  "debug.track_token_usage",
] as const;

const LLM_DISCOVERY_COMMON_PATHS = [
  "llm.discovery.enabled",
  "llm.discovery.timeout",
  "llm.discovery.auto_adjust",
] as const;

const ANALYSIS_COMMON_PATHS = [
  "analysis.data_dir",
  "analysis.feedback_dir",
] as const;

const GIT_COMMIT_MODEL_COMMON_PATHS = [
  "git.commit_message_model_ref",
] as const;

const GIT_COMMIT_PROMPT_COMMON_PATHS = [
  "git.commit_message_prompt",
] as const;

const USER_PROFILE_COMMON_PATHS = [
  "user_profile.display_name",
  "user_profile.avatar_preset",
  "user_profile.avatar_image_path",
] as const;

const SECTION_PRESENTATION: Record<
  ConfigSectionPresentationLanguage,
  Record<string, ProgressiveConfigSectionPresentation>
> = {
  zh: {
    "user-profile": {
      sectionTitle: "用户资料与头像",
      sectionSummary: "先设置工作台显示名和头像；只有需要时再补充提供给 Agent 的背景与偏好。",
      commonPaths: USER_PROFILE_COMMON_PATHS,
      commonTitle: "基础资料",
      commonHint: "设置工作台显示名与头像，即可完成日常资料配置。",
      advancedTitle: "Agent 参考信息（高级）",
      advancedHint: "用户背景与偏好会进入 Agent 上下文，仅在需要个性化协作时补充。",
      advancedCountLabel: (count) => `${count} 项`,
    },
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
    ui: {
      sectionTitle: "界面显示",
      commonPaths: UI_COMMON_PATHS,
      commonTitle: "常用设置",
      commonHint: "先设置语言、配色和工作台欢迎内容。",
      advancedTitle: "高级设置",
      advancedHint: "刷新频率、日志容量和背景图片通常不需要频繁修改。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    security: {
      sectionTitle: "安全限制",
      commonPaths: SECURITY_COMMON_PATHS,
      commonTitle: "常用设置",
      commonHint: "日常只需确认安全限制是否启用。",
      advancedTitle: "高级设置",
      advancedHint: "目录白名单、文件保护和危险命令规则建议保持默认。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    network: {
      sectionTitle: "网络连接",
      commonPaths: NETWORK_COMMON_PATHS,
      commonTitle: "常用设置",
      commonHint: "超时、代理开关和代理地址覆盖日常联网需要。",
      advancedTitle: "高级设置",
      advancedHint: "请求标识、重试和 SSL 校验通常保持默认。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    log: {
      sectionTitle: "日志记录",
      commonPaths: LOG_COMMON_PATHS,
      commonTitle: "常用设置",
      commonHint: "选择日志级别，并决定是否写入文件和保留详细错误。",
      advancedTitle: "高级设置",
      advancedHint: "日志格式、轮转和第三方库级别仅在排障时调整。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    debug: {
      sectionTitle: "调试追踪",
      commonPaths: DEBUG_COMMON_PATHS,
      commonTitle: "常用设置",
      commonHint: "调试总开关与 Token 用量记录是最常用的两项。",
      advancedTitle: "高级设置",
      advancedHint: "详细输出、LLM 和工具追踪会增加日志量，按需开启。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    "llm-discovery": {
      sectionTitle: "模型发现",
      sectionSummary: "控制工作台如何发现模型，以及无法读取模型限制时使用的回退值。",
      commonPaths: LLM_DISCOVERY_COMMON_PATHS,
      commonTitle: "常用设置",
      commonHint: "日常只需决定是否启用、等待多久以及是否自动适配模型限制。",
      advancedTitle: "回退参数",
      advancedHint: "只有发现结果不准确时，才需要调整令牌上限和输出预留比例。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    analysis: {
      sectionTitle: "分析数据存储",
      sectionSummary: "设置分析结果、反馈数据和知识资产在工作区中的存放位置。",
      layout: "compact_paths",
      commonPaths: ANALYSIS_COMMON_PATHS,
      commonTitle: "常用目录",
      commonHint: "日常只需指定分析结果与反馈数据目录。",
      advancedTitle: "知识资产路径",
      advancedHint: "知识图谱与模式库文件位置通常保持默认。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    "git-commit-model": {
      sectionTitle: "Git 提交助手",
      sectionSummary: "选择生成提交说明时使用的模型；通常只需要配置这一项。",
      layout: "compact_paths",
      commonPaths: GIT_COMMIT_MODEL_COMMON_PATHS,
      commonTitle: "模型选择",
      commonHint: "从模型库中选择生成提交说明时使用的模型。",
      advancedTitle: "高级设置",
      advancedHint: "此分区没有额外高级参数。",
      advancedCountLabel: (count) => `${count} 项`,
    },
    "git-commit-prompt": {
      sectionTitle: "提示词模板（高级）",
      sectionSummary: "只有默认提交说明格式不满足需要时才修改，并保留 {diff} 占位符。",
      commonPaths: GIT_COMMIT_PROMPT_COMMON_PATHS,
      commonTitle: "模板内容",
      commonHint: "修改前确认 {diff} 占位符仍然存在。",
      advancedTitle: "高级设置",
      advancedHint: "此分区没有额外高级参数。",
      advancedCountLabel: (count) => `${count} 项`,
    },
  },
  en: {
    "user-profile": {
      sectionTitle: "Profile and avatar",
      sectionSummary: "Set the workbench display name and avatar first; add Agent background and preferences only when needed.",
      commonPaths: USER_PROFILE_COMMON_PATHS,
      commonTitle: "Basic profile",
      commonHint: "A display name and avatar are enough for everyday use.",
      advancedTitle: "Agent reference information (advanced)",
      advancedHint: "Background and preferences enter the Agent context; add them only when personalized collaboration needs them.",
      advancedCountLabel: (count) => `${count} fields`,
    },
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
    ui: {
      sectionTitle: "Interface",
      commonPaths: UI_COMMON_PATHS,
      commonTitle: "Common settings",
      commonHint: "Choose the language, color theme, and welcome content first.",
      advancedTitle: "Advanced settings",
      advancedHint: "Refresh cadence, log capacity, and background imagery rarely need adjustment.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    security: {
      sectionTitle: "Security limits",
      commonPaths: SECURITY_COMMON_PATHS,
      commonTitle: "Common settings",
      commonHint: "For everyday use, confirm whether security limits are enabled.",
      advancedTitle: "Advanced settings",
      advancedHint: "Directory allowlists, protected files, and dangerous command rules should usually keep their defaults.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    network: {
      sectionTitle: "Network connection",
      commonPaths: NETWORK_COMMON_PATHS,
      commonTitle: "Common settings",
      commonHint: "Timeout and proxy controls cover the usual network setup.",
      advancedTitle: "Advanced settings",
      advancedHint: "Request identity, retries, and SSL verification usually keep their defaults.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    log: {
      sectionTitle: "Logging",
      commonPaths: LOG_COMMON_PATHS,
      commonTitle: "Common settings",
      commonHint: "Choose the log level, file output, and detailed error behavior.",
      advancedTitle: "Advanced settings",
      advancedHint: "Formatting, rotation, and third-party levels are mainly for troubleshooting.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    debug: {
      sectionTitle: "Debug tracing",
      commonPaths: DEBUG_COMMON_PATHS,
      commonTitle: "Common settings",
      commonHint: "The debug switch and token usage tracking are the usual controls.",
      advancedTitle: "Advanced settings",
      advancedHint: "Verbose, LLM, and tool tracing increase log volume and should be enabled only when needed.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    "llm-discovery": {
      sectionTitle: "Model discovery",
      sectionSummary: "Control model discovery and the fallback limits used when a provider cannot report them.",
      commonPaths: LLM_DISCOVERY_COMMON_PATHS,
      commonTitle: "Common settings",
      commonHint: "Choose whether to discover models, how long to wait, and whether limits adjust automatically.",
      advancedTitle: "Fallback parameters",
      advancedHint: "Adjust token limits and output reserve only when discovery results are incomplete.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    analysis: {
      sectionTitle: "Analysis data storage",
      sectionSummary: "Choose where analysis results, feedback, and knowledge assets are stored in the workspace.",
      layout: "compact_paths",
      commonPaths: ANALYSIS_COMMON_PATHS,
      commonTitle: "Common directories",
      commonHint: "Everyday setup only needs the analysis and feedback directories.",
      advancedTitle: "Knowledge asset paths",
      advancedHint: "Knowledge graph and pattern library files usually keep their defaults.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    "git-commit-model": {
      sectionTitle: "Git commit assistant",
      sectionSummary: "Choose the model used to generate commit messages; this is normally the only setting you need.",
      layout: "compact_paths",
      commonPaths: GIT_COMMIT_MODEL_COMMON_PATHS,
      commonTitle: "Model selection",
      commonHint: "Select a model-library entry for commit message generation.",
      advancedTitle: "Advanced settings",
      advancedHint: "This section has no additional advanced fields.",
      advancedCountLabel: (count) => `${count} fields`,
    },
    "git-commit-prompt": {
      sectionTitle: "Prompt template (advanced)",
      sectionSummary: "Edit only when the default commit format is insufficient, and keep the {diff} placeholder.",
      commonPaths: GIT_COMMIT_PROMPT_COMMON_PATHS,
      commonTitle: "Template content",
      commonHint: "Confirm that the {diff} placeholder remains after editing.",
      advancedTitle: "Advanced settings",
      advancedHint: "This section has no additional advanced fields.",
      advancedCountLabel: (count) => `${count} fields`,
    },
  },
};

const ZH_FIELD_COPY: Record<string, ConfigFieldPresentationCopy> = {
  "ui.language": { label: "界面语言", hint: "切换工作台界面使用的语言。" },
  "ui.theme": { label: "配色主题", hint: "选择工作台的基础配色方案。" },
  "ui.max_log_entries": { label: "界面日志保留条数", hint: "限制工作台内存中保留的日志条目数量。" },
  "ui.refresh_rate": { label: "界面刷新频率", hint: "控制终端工作台刷新状态的频率。" },
  "ui.show_ascii_art": { label: "显示 ASCII 图案", hint: "在支持的终端界面显示启动图案。" },
  "ui.show_welcome": { label: "显示欢迎面板", hint: "进入工作台时显示欢迎内容。" },
  "ui.workbench_theme": { label: "工作台背景", hint: "设置背景图片及其内容可读性。" },
  "ui.workbench_theme.background_image_path": { label: "工作台背景图片", hint: "上传或选择工作台使用的本地背景图片。" },
  "ui.workbench_theme.background_readability": { label: "背景可读性", hint: "调整遮罩和面板透明度，确保文字清晰。" },
  "security.enabled": { label: "启用安全限制", hint: "启用目录、文件和危险命令保护规则。" },
  "security.allowed_directories": { label: "允许访问的目录", hint: "工具被允许访问的目录范围，一行一个。" },
  "security.forbidden_patterns": { label: "禁止访问的文件规则", hint: "匹配敏感文件名的保护规则，一行一个。" },
  "security.forbidden_delete_patterns": { label: "禁止删除的文件规则", hint: "即使允许访问，也不能删除的关键文件规则。" },
  "security.dangerous_commands": { label: "危险命令拦截规则", hint: "命中后会阻止执行的破坏性命令模式。" },
  "network.timeout": { label: "请求超时（秒）", hint: "单次网络请求允许等待的最长时间。" },
  "network.user_agent": { label: "请求标识", hint: "公网请求使用的 User-Agent 标识。" },
  "network.max_retries": { label: "最大重试次数", hint: "网络请求失败后允许自动重试的次数。" },
  "network.retry_delay": { label: "重试等待时间（秒）", hint: "两次网络重试之间的等待时间。" },
  "network.verify_ssl": { label: "验证 SSL 证书", hint: "验证 HTTPS 服务的证书有效性，建议保持开启。" },
  "network.proxy_enabled": { label: "启用代理", hint: "启用后，真实公网请求会通过下方代理地址访问。" },
  "network.proxy_url": { label: "代理地址", hint: "填写 HTTP/HTTPS 代理地址，例如 http://127.0.0.1:7890。" },
  "parser.strip_tags": { label: "移除的内部标签", hint: "从模型输出中清理的内部标签，一行一个。" },
  "parser.strip_thinking_alias": { label: "移除思考标签别名", hint: "清理兼容模型返回的思考标签别名。" },
  "log.level": { label: "日志级别", hint: "控制 Vibelution 记录日志的最低级别。" },
  "log.format": { label: "日志格式", hint: "定义每条日志的输出格式。" },
  "log.date_format": { label: "日志时间格式", hint: "定义日志时间戳的显示格式。" },
  "log.file_enabled": { label: "写入日志文件", hint: "将运行日志同时写入本地文件。" },
  "log.file_path": { label: "日志文件路径", hint: "启用文件日志后使用的相对或绝对路径。" },
  "log.max_file_size": { label: "单个日志最大字节数", hint: "日志文件达到该大小后进行轮转。" },
  "log.backup_count": { label: "保留日志备份数", hint: "日志轮转后最多保留的历史文件数量。" },
  "log.detailed_traceback": { label: "记录详细错误堆栈", hint: "发生异常时记录完整堆栈，便于排障。" },
  "log.third_party": { label: "第三方库日志级别", hint: "分别控制常用依赖库的日志噪声。" },
  "log.third_party.httpx": { label: "HTTPX 日志级别" },
  "log.third_party.httpcore": { label: "HTTPCore 日志级别" },
  "log.third_party.langchain": { label: "LangChain 日志级别" },
  "log.third_party.openai": { label: "OpenAI 日志级别" },
  "log.third_party.anthropic": { label: "Anthropic 日志级别" },
  "log.third_party.urllib3": { label: "urllib3 日志级别" },
  "log.third_party.litellm": { label: "LiteLLM 日志级别" },
  "log.third_party.rich": { label: "Rich 日志级别" },
  "debug.enabled": { label: "启用调试模式", hint: "开启额外的调试信息记录。" },
  "debug.verbose": { label: "输出详细调试信息", hint: "记录更详细的调试过程，会增加日志量。" },
  "debug.trace_llm": { label: "追踪 LLM 调用", hint: "记录模型调用阶段与结果状态，不记录密钥。" },
  "debug.trace_tools": { label: "追踪工具调用", hint: "记录工具执行阶段与结果状态。" },
  "debug.track_token_usage": { label: "记录 Token 用量", hint: "统计模型调用消耗的 Token 数量。" },
  "llm.discovery.enabled": { label: "启用自动发现", hint: "连接服务商后自动读取可用模型列表。" },
  "llm.discovery.timeout": { label: "发现等待时间（秒）", hint: "服务商响应超过该时间后停止本次发现。" },
  "llm.discovery.auto_adjust": { label: "自动适配模型限制", hint: "发现模型能力后自动校正上下文与输出上限。" },
  "llm.discovery.fallback_max_tokens": { label: "默认输出上限", hint: "无法读取模型输出上限时使用的保守值。" },
  "llm.discovery.fallback_max_token_limit": { label: "默认上下文上限", hint: "无法读取模型上下文窗口时使用的保守值。" },
  "llm.discovery.output_reserve_ratio": { label: "输出预留比例", hint: "从上下文窗口中为模型回复预留的比例。" },
  "analysis.data_dir": { label: "分析数据目录", hint: "保存分析结果和统计数据的工作区目录。" },
  "analysis.feedback_dir": { label: "反馈数据目录", hint: "保存人工反馈与评估反馈的工作区目录。" },
  "analysis.knowledge_graph_path": { label: "知识图谱文件", hint: "分析流程读取和更新知识图谱的文件路径。" },
  "analysis.pattern_library_path": { label: "模式库文件", hint: "保存可复用分析模式的文件路径。" },
  "git.commit_message_model_ref": { label: "Git 提交使用的模型", hint: "选择用于生成提交说明的模型库条目。" },
  "git.commit_message_prompt": { label: "提交说明提示词模板", hint: "仅在需要定制格式时修改，并保留 {diff} 占位符。" },
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
  "ui.language": { label: "Interface language" },
  "ui.theme": { label: "Color theme" },
  "ui.show_ascii_art": { label: "Show ASCII artwork" },
  "ui.show_welcome": { label: "Show welcome panel" },
  "security.enabled": { label: "Enable security limits" },
  "network.timeout": { label: "Request timeout" },
  "network.proxy_enabled": { label: "Enable proxy" },
  "network.proxy_url": { label: "Proxy URL" },
  "log.level": { label: "Log level" },
  "log.file_enabled": { label: "Write log file" },
  "log.file_path": { label: "Log file path" },
  "log.detailed_traceback": { label: "Detailed traceback" },
  "debug.enabled": { label: "Enable debug mode" },
  "debug.track_token_usage": { label: "Track token usage" },
  "llm.discovery.enabled": { label: "Enable automatic discovery", hint: "Load available models after connecting a provider." },
  "llm.discovery.timeout": { label: "Discovery timeout", hint: "Stop the discovery request after this many seconds." },
  "llm.discovery.auto_adjust": { label: "Adjust model limits automatically", hint: "Update context and output limits from discovered capabilities." },
  "llm.discovery.fallback_max_tokens": { label: "Default output limit", hint: "Used when the provider does not report an output limit." },
  "llm.discovery.fallback_max_token_limit": { label: "Default context limit", hint: "Used when the provider does not report a context window." },
  "llm.discovery.output_reserve_ratio": { label: "Output reserve ratio", hint: "Reserve this share of the context window for the model response." },
  "analysis.data_dir": { label: "Analysis data directory", hint: "Workspace directory for analysis results and statistics." },
  "analysis.feedback_dir": { label: "Feedback data directory", hint: "Workspace directory for human and evaluation feedback." },
  "analysis.knowledge_graph_path": { label: "Knowledge graph file", hint: "File read and updated by the analysis knowledge graph flow." },
  "analysis.pattern_library_path": { label: "Pattern library file", hint: "File containing reusable analysis patterns." },
  "git.commit_message_model_ref": { label: "Commit message model", hint: "Model-library entry used to generate commit messages." },
  "git.commit_message_prompt": { label: "Commit message prompt template", hint: "Edit only to customize the format, and keep the {diff} placeholder." },
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

export function configSectionExpandedByDefault(sectionId: string): boolean {
  return sectionId !== "git-commit-prompt";
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
