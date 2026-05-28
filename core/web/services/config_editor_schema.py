"""Shared config editor schema helpers for the web workbench."""

from __future__ import annotations

import copy
from typing import Any


RUNTIME_PROFILE_OPTIONS = ["safe_local", "safe_remote", "debug", "ci"]
AGENT_MODE_OPTIONS = ["chat", "self_evolution", "supervised_evolution"]
SEGMENTATION_STRATEGY_OPTIONS = ["task_contiguous"]
AVATAR_PRESET_OPTIONS = ["lobster", "shrimp", "crab", "cat", "chick", "bunny", "slime", "penguin", "moose"]
USER_AVATAR_PRESET_OPTIONS = ["default", "circle", "spark", "codex", "minimal", "initial"]
WORKBENCH_WINDOW_MODE_OPTIONS = ["windowed", "fullscreen"]

SECTION_LABELS = {
    "zh": {
        "runtime": "运行时",
        "workbench": "工作台启动",
        "avatar": "形象",
        "user_profile": "用户信息",
        "llm.profiles": "模型配置",
        "llm.discovery": "模型发现",
        "agent": "智能体",
        "context_compression": "上下文压缩",
        "tools": "工具",
        "security": "安全",
        "log": "日志",
        "network": "网络",
        "evolution": "进化",
        "memory": "记忆",
        "strategy": "策略",
        "analysis": "分析",
        "ui": "界面",
        "parser": "解析器",
        "prompt": "系统提示词",
        "git.commit_message_profile": "Git 提交模型",
        "git.commit_message_prompt": "Git 提交提示词",
        "debug": "调试",
        "pet": "宠物",
    },
    "en": {
        "runtime": "Runtime",
        "workbench": "Workbench Startup",
        "avatar": "Avatar",
        "user_profile": "User Info",
        "llm.profiles": "Model Configs",
        "llm.discovery": "Model Discovery",
        "agent": "Agent",
        "context_compression": "Context Compression",
        "tools": "Tools",
        "security": "Security",
        "log": "Logging",
        "network": "Network",
        "evolution": "Evolution",
        "memory": "Memory",
        "strategy": "Strategy",
        "analysis": "Analysis",
        "ui": "UI",
        "parser": "Parser",
        "prompt": "System Prompts",
        "git.commit_message_profile": "Git Commit Model",
        "git.commit_message_prompt": "Git Commit Prompt",
        "debug": "Debug",
        "pet": "Pet",
    },
}

FIELD_LABELS = {
    "zh": {
        "runtime.profile": "运行档位",
        "runtime.preflight_doctor": "启动前自检",
        "runtime.require_venv": "要求使用 .venv",
        "workbench.backend_port": "后端服务端口",
        "workbench.frontend_port": "前端页面端口",
        "workbench.window_mode": "窗口模式",
        "avatar.preset": "形象预设",
        "user_profile.display_name": "用户显示名",
        "user_profile.bio": "用户背景",
        "user_profile.preferences": "用户偏好",
        "user_profile.avatar_preset": "用户头像",
        "user_profile.avatar_image_path": "本地头像图片",
        "llm.profiles.primary.provider_id": "模型服务绑定",
        "llm.profiles.primary.model": "模型名称",
        "llm.profiles.primary.temperature": "温度",
        "llm.profiles.primary.max_output_tokens": "最大输出令牌数",
        "llm.profiles.primary.timeout": "API 超时（秒）",
        "llm.profiles.primary.connect_timeout": "连接超时（秒）",
        "llm.profiles.primary.streaming": "启用流式响应",
        "llm.profiles.primary.tool_calling_mode": "工具调用模式",
        "llm.discovery.enabled": "启用模型发现",
        "llm.discovery.timeout": "发现超时（秒）",
        "llm.discovery.fallback_max_tokens": "回退最大令牌数",
        "llm.discovery.fallback_max_token_limit": "回退上下文上限",
        "llm.discovery.auto_adjust": "自动调整",
        "llm.discovery.output_reserve_ratio": "输出预留比例",
        "agent.name": "智能体名称",
        "agent.workspace": "工作目录",
        "agent.awake_interval": "苏醒间隔（秒）",
        "agent.max_iterations": "最大工具调用数",
        "agent.max_runtime": "最大运行时长（秒）",
        "agent.auto_backup": "自动备份",
        "agent.backup_interval": "备份间隔（秒）",
        "agent.auto_restart_threshold": "自动重启阈值",
        "agent.exploration_mode": "探索模式",
        "agent.default_mode": "默认运行模式",
        "agent.modes.chat_enabled": "启用 chat 模式",
        "agent.modes.self_evolution_enabled": "启用自进化模式",
        "agent.modes.supervised_evolution_enabled": "启用监督进化模式",
        "agent.modes.default_shell_mode": "工作台默认模式",
        "agent.modes.default_headless_mode": "无交互默认模式",
        "context_compression.keep_recent_steps": "保留最近步骤数",
        "context_compression.max_compressions_per_session": "每会话最大压缩次数",
        "context_compression.effectiveness_threshold": "压缩有效性阈值",
        "context_compression.preservation.keep_ai_messages": "保留 AI 消息数",
        "context_compression.preservation.preserve_errors": "保留错误",
        "context_compression.preservation.extract_key_decisions": "提取关键决策",
        "tools.file.encoding_priority": "编码优先级",
        "tools.file.editable_extensions": "可编辑扩展名",
        "tools.shell.max_output_length": "最大输出长度",
        "tools.shell.safety_check": "安全检查",
        "tools.shell.dangerous_pattern_check": "危险模式检查",
        "tools.shell.allowed_shells": "允许的 Shell",
        "tools.search.max_matches_per_file": "单文件最大匹配数",
        "tools.search.skip_directories": "跳过目录",
        "tools.search.skip_extensions": "跳过扩展名",
        "tools.image2.default_model_ref": "默认生图模型",
        "ui.language": "界面语言",
        "ui.theme": "主题",
        "ui.max_log_entries": "最大日志条目数",
        "ui.refresh_rate": "刷新频率",
        "ui.show_ascii_art": "显示 ASCII Art",
        "ui.show_welcome": "显示欢迎面板",
        "prompt.default_components": "默认提示词组件",
        "git.commit_message_profile": "Git 提交使用的模型配置",
        "git.commit_message_prompt": "AI 提交说明提示词",
        "network.proxy_enabled": "启用代理",
        "network.proxy_url": "代理地址",
        "evolution.chat_dataset.enabled": "启用 chat 数据采样",
        "evolution.chat_dataset.source_modes": "采样来源模式",
        "evolution.chat_dataset.auto_capture": "自动采样",
        "evolution.chat_dataset.segmentation_strategy": "分段策略",
        "evolution.chat_dataset.min_turns": "最少轮数",
        "evolution.chat_dataset.max_turns": "最多轮数",
        "evolution.chat_dataset.require_tool_call_or_analysis_or_conclusion": "要求工具/分析/结论信号",
        "evolution.chat_dataset.exclude_pure_chitchat": "排除纯闲聊",
        "evolution.chat_dataset.candidate_dir": "候选目录",
        "evolution.chat_dataset.review_queue_path": "审核队列路径",
        "evolution.chat_dataset.approved_raw_dir": "已批准原始目录",
        "evolution.chat_dataset.approved_jsonl_path": "已批准数据集路径",
        "evolution.chat_dataset.rejected_log_path": "拒绝审计路径",
    },
    "en": {
        "runtime.profile": "Runtime Mode",
        "runtime.preflight_doctor": "Preflight Doctor",
        "runtime.require_venv": "Require .venv",
        "workbench.backend_port": "Backend Service Port",
        "workbench.frontend_port": "Frontend Page Port",
        "workbench.window_mode": "Workbench Window Mode",
        "avatar.preset": "Avatar Preset",
        "user_profile.display_name": "User Display Name",
        "user_profile.bio": "User Background",
        "user_profile.preferences": "User Preferences",
        "user_profile.avatar_preset": "User Avatar",
        "user_profile.avatar_image_path": "Local Avatar Image",
        "llm.profiles.primary.provider_id": "Provider Binding",
        "llm.profiles.primary.model": "Model Name",
        "llm.profiles.primary.temperature": "Temperature",
        "llm.profiles.primary.max_output_tokens": "Max Output Tokens",
        "llm.profiles.primary.timeout": "API Timeout (s)",
        "llm.profiles.primary.connect_timeout": "Connect Timeout (s)",
        "llm.profiles.primary.streaming": "Streaming",
        "llm.profiles.primary.tool_calling_mode": "Tool Calling Mode",
        "llm.discovery.enabled": "Enable Discovery",
        "llm.discovery.timeout": "Discovery Timeout (s)",
        "llm.discovery.fallback_max_tokens": "Fallback Max Tokens",
        "llm.discovery.fallback_max_token_limit": "Fallback Token Limit",
        "llm.discovery.auto_adjust": "Auto Adjust",
        "llm.discovery.output_reserve_ratio": "Output Reserve Ratio",
        "agent.name": "Agent Name",
        "agent.workspace": "Workspace",
        "agent.awake_interval": "Wake Interval (s)",
        "agent.max_iterations": "Max Tool Calls",
        "agent.max_runtime": "Max Runtime (s)",
        "agent.auto_backup": "Auto Backup",
        "agent.backup_interval": "Backup Interval (s)",
        "agent.auto_restart_threshold": "Auto Restart Threshold",
        "agent.exploration_mode": "Exploration Mode",
        "agent.default_mode": "Default Agent Mode",
        "agent.modes.chat_enabled": "Enable Chat Mode",
        "agent.modes.self_evolution_enabled": "Enable Self Evolution",
        "agent.modes.supervised_evolution_enabled": "Enable Supervised Evolution",
        "agent.modes.default_shell_mode": "Default Workbench Mode",
        "agent.modes.default_headless_mode": "Default Headless Mode",
        "context_compression.keep_recent_steps": "Recent Steps to Keep",
        "context_compression.max_compressions_per_session": "Max Compressions Per Session",
        "context_compression.effectiveness_threshold": "Compression Effectiveness Threshold",
        "context_compression.preservation.keep_ai_messages": "AI Messages to Keep",
        "context_compression.preservation.preserve_errors": "Preserve Errors",
        "context_compression.preservation.extract_key_decisions": "Extract Key Decisions",
        "tools.file.encoding_priority": "Encoding Priority",
        "tools.file.editable_extensions": "Editable Extensions",
        "tools.shell.max_output_length": "Max Output Length",
        "tools.shell.safety_check": "Safety Check",
        "tools.shell.dangerous_pattern_check": "Dangerous Pattern Check",
        "tools.shell.allowed_shells": "Allowed Shells",
        "tools.search.max_matches_per_file": "Max Matches Per File",
        "tools.search.skip_directories": "Skip Directories",
        "tools.search.skip_extensions": "Skip Extensions",
        "tools.image2.default_model_ref": "Default Image Model",
        "ui.language": "Interface Language",
        "ui.theme": "Theme",
        "ui.max_log_entries": "Max Log Entries",
        "ui.refresh_rate": "Refresh Rate",
        "ui.show_ascii_art": "Show ASCII Art",
        "ui.show_welcome": "Show Welcome Panel",
        "prompt.default_components": "Default Prompt Components",
        "git.commit_message_profile": "Git Commit Model Config",
        "git.commit_message_prompt": "AI Commit Message Prompt",
        "network.proxy_enabled": "Enable Proxy",
        "network.proxy_url": "Proxy URL",
        "evolution.chat_dataset.enabled": "Enable Chat Dataset Capture",
        "evolution.chat_dataset.source_modes": "Capture Source Modes",
        "evolution.chat_dataset.auto_capture": "Auto Capture",
        "evolution.chat_dataset.segmentation_strategy": "Segmentation Strategy",
        "evolution.chat_dataset.min_turns": "Minimum Turns",
        "evolution.chat_dataset.max_turns": "Maximum Turns",
        "evolution.chat_dataset.require_tool_call_or_analysis_or_conclusion": "Require Tool/Analysis/Conclusion Signal",
        "evolution.chat_dataset.exclude_pure_chitchat": "Exclude Pure Chitchat",
        "evolution.chat_dataset.candidate_dir": "Candidate Directory",
        "evolution.chat_dataset.review_queue_path": "Review Queue Path",
        "evolution.chat_dataset.approved_raw_dir": "Approved Raw Directory",
        "evolution.chat_dataset.approved_jsonl_path": "Approved Dataset Path",
        "evolution.chat_dataset.rejected_log_path": "Rejected Audit Path",
    },
}

FIELD_SUFFIX_LABELS = {
    "zh": {
        "provider": "服务提供方",
        "kind": "类型",
        "provider.kind": "服务商类型",
        "api_key_env": "密钥环境变量",
        "provider.api_key_env": "服务商密钥环境变量",
        "base_url": "基础地址",
        "provider.base_url": "服务商基础地址",
        "compat_mode": "兼容模式",
        "provider.compat_mode": "服务商兼容模式",
        "context_window": "上下文窗口",
        "provider.context_window": "服务商上下文窗口",
        "requires_api_key": "需要 API Key",
        "provider.requires_api_key": "服务商需要 API Key",
        "transport": "传输协议",
        "contract": "交互契约",
        "reasoning_state_field": "推理状态字段",
        "tool_calling_mode": "工具调用模式",
        "strict_compatibility": "严格兼容",
        "temperature": "温度",
        "max_output_tokens": "最大输出令牌数",
        "timeout": "超时（秒）",
        "connect_timeout": "连接超时（秒）",
        "streaming": "启用流式响应",
        "discovery_enabled": "启用模型发现",
        "label": "显示名",
        "model": "模型名称",
        "model_id": "模型 ID",
    },
    "en": {
        "provider": "Provider",
        "kind": "Kind",
        "provider.kind": "Provider Kind",
        "api_key_env": "API Key Env",
        "provider.api_key_env": "Provider API Key Env",
        "base_url": "Base URL",
        "provider.base_url": "Provider Base URL",
        "compat_mode": "Compat Mode",
        "provider.compat_mode": "Provider Compat Mode",
        "context_window": "Context Window",
        "provider.context_window": "Provider Context Window",
        "requires_api_key": "Requires API Key",
        "provider.requires_api_key": "Provider Requires API Key",
        "transport": "Transport",
        "contract": "Contract",
        "reasoning_state_field": "Reasoning State Field",
        "tool_calling_mode": "Tool Calling Mode",
        "strict_compatibility": "Strict Compatibility",
        "temperature": "Temperature",
        "max_output_tokens": "Max Output Tokens",
        "timeout": "Timeout (s)",
        "connect_timeout": "Connect Timeout (s)",
        "streaming": "Streaming",
        "discovery_enabled": "Discovery Enabled",
        "label": "Label",
        "model": "Model Name",
        "model_id": "Model ID",
    },
}

BADGE_LABELS = {
    "zh": {
        "Group": "分组",
        "List": "列表",
        "Toggle": "开关",
        "Option": "选项",
        "Seconds": "秒",
        "Token": "令牌",
        "Number": "数字",
        "JSON": "JSON",
        "Secret": "密钥",
        "URL": "地址",
        "Path": "路径",
        "Text": "文本",
        "Multiline": "多行文本",
        "Image": "图片",
    },
    "en": {
        "Group": "Group",
        "List": "List",
        "Toggle": "Toggle",
        "Option": "Option",
        "Seconds": "Seconds",
        "Token": "Token",
        "Number": "Number",
        "JSON": "JSON",
        "Secret": "Secret",
        "URL": "URL",
        "Path": "Path",
        "Text": "Text",
        "Multiline": "Multiline",
        "Image": "Image",
    },
}

FIELD_HINTS = {
    "zh": {
        "runtime.profile": "决定默认运行策略，通常先从 safe_local 或 debug 开始。",
        "runtime.preflight_doctor": "启动前先做自检，适合排查环境漂移。",
        "workbench.backend_port": "后端服务监听的本地端口，修改后下次启动或重启生效。",
        "workbench.frontend_port": "前端页面使用的本地端口，修改后下次启动或重启生效。",
        "workbench.window_mode": "窗口化保留系统标题栏；沉浸全屏会隐藏原生标题栏，修改后重启工作台生效。",
        "agent.awake_interval": "自主模式两次苏醒之间的间隔。",
        "agent.max_iterations": "单轮最多允许多少次工具动作。",
        "agent.max_runtime": "单轮可持续的最长运行时间。",
        "agent.default_mode": "决定默认启动为 chat、自进化还是监督进化。",
        "agent.modes.default_shell_mode": "工作台入口默认采用的 agent mode。",
        "agent.modes.default_headless_mode": "命令行无交互运行时默认采用的 agent mode。",
        "agent.auto_restart_threshold": "达到阈值后触发热重启。",
        "context_compression.keep_recent_steps": "压缩后仍然保留的最近步骤数。",
        "context_compression.max_compressions_per_session": "单会话允许的最大压缩次数。",
        "tools.shell.allowed_shells": "允许使用的 shell 类型，直接影响跨平台行为。",
        "tools.shell.max_output_length": "终端输出截断上限，过小会影响诊断。",
        "tools.image2.default_model_ref": "image2_generate_tool 默认使用的模型库条目；留空时回退到 VIBELUTION_IMAGE2_MODEL 或内置模型名。",
        "evolution.chat_dataset.source_modes": "哪些 agent mode 产生的对话可以被静默采样进入审核队列。",
        "evolution.chat_dataset.segmentation_strategy": "chat 采样如何切分连续多轮上下文。",
        "ui.refresh_rate": "终端工作台刷新频率。",
        "ui.max_log_entries": "UI 内部保留的日志条目数。",
        "git.commit_message_profile": "Git 页面点击“AI 生成说明”时使用哪一个 LLM 配置。",
        "git.commit_message_prompt": "Git 页面生成提交说明时使用的系统提示词模板。可使用 {summary}、{files}、{diff}、{branch} 占位符。",
        "network.proxy_enabled": "启用后，科研调研等真实公网请求会通过下方代理地址访问。",
        "network.proxy_url": "填写 HTTP/HTTPS 代理地址，例如 http://127.0.0.1:7890。",
        "user_profile.display_name": "用于工作台和对话消息的用户名称；为空时回退到系统用户名。",
        "user_profile.bio": "简短用户背景，会作为 agent 的参考依据进入系统提示词。",
        "user_profile.preferences": "用户偏好列表，会作为 agent 的参考依据进入系统提示词。",
        "user_profile.avatar_preset": "用户头像预设，仅用于前端显示，不把图片内容传给模型。",
        "user_profile.avatar_image_path": "上传本地图片后会复制到项目头像目录，仅用于前端显示，不把图片内容传给模型。",
    },
    "en": {
        "runtime.profile": "Sets the default runtime posture. Start with safe_local or debug in most cases.",
        "runtime.preflight_doctor": "Runs startup checks before execution to catch environment drift.",
        "workbench.backend_port": "Local port listened on by the backend service. Restart the workbench after changing it.",
        "workbench.frontend_port": "Local port used by the frontend page. Restart the workbench after changing it.",
        "workbench.window_mode": "Windowed mode keeps the native title bar; immersive fullscreen hides it. Restart the workbench after changing it.",
        "agent.awake_interval": "Delay between autonomous wake cycles.",
        "agent.max_iterations": "Maximum tool actions allowed in one round.",
        "agent.max_runtime": "Maximum duration for a single round.",
        "agent.default_mode": "Selects whether the agent defaults to chat, self-evolution, or supervised evolution.",
        "agent.modes.default_shell_mode": "Agent mode used by default when entering the interactive workbench.",
        "agent.modes.default_headless_mode": "Agent mode used by default for non-interactive CLI runs.",
        "agent.auto_restart_threshold": "Threshold that triggers hot restart.",
        "context_compression.keep_recent_steps": "How many recent steps survive compression.",
        "context_compression.max_compressions_per_session": "Compression cap per session.",
        "tools.shell.allowed_shells": "Allowed shell types. This directly affects cross-platform behavior.",
        "tools.shell.max_output_length": "Terminal output cap. Too small will hide diagnostics.",
        "tools.image2.default_model_ref": "Model library entry used by image2_generate_tool. Empty falls back to VIBELUTION_IMAGE2_MODEL or the built-in model name.",
        "evolution.chat_dataset.source_modes": "Which agent modes may silently contribute conversation samples to the review queue.",
        "evolution.chat_dataset.segmentation_strategy": "How chat capture segments contiguous multi-turn context.",
        "ui.refresh_rate": "Refresh cadence for the terminal workbench.",
        "ui.max_log_entries": "How many UI log entries are retained.",
        "git.commit_message_profile": "LLM config used by the AI commit message button on the Git page.",
        "git.commit_message_prompt": "System prompt template for generated commit messages. Supports {summary}, {files}, {diff}, and {branch}.",
        "network.proxy_enabled": "When enabled, real public research requests use the proxy URL below.",
        "network.proxy_url": "HTTP/HTTPS proxy URL, for example http://127.0.0.1:7890.",
        "user_profile.display_name": "User name used by the workbench and chat messages. Falls back to the OS user name when empty.",
        "user_profile.bio": "Short user background included as agent reference context.",
        "user_profile.preferences": "User preference list included as agent reference context.",
        "user_profile.avatar_preset": "User avatar preset for frontend display only. Image content is not sent to the model.",
        "user_profile.avatar_image_path": "Local image uploads are copied into the project avatar directory for frontend display only. Image content is not sent to the model.",
    },
}

EDITOR_SECTION_SPECS = [
    ("runtime", "runtime"),
    ("workbench", "workbench"),
    ("avatar", "avatar"),
    ("user-profile", "user_profile"),
    ("llm-profiles", "llm.profiles"),
    ("llm-discovery", "llm.discovery"),
    ("agent", "agent"),
    ("context-compression", "context_compression"),
    ("tools", "tools"),
    ("security", "security"),
    ("log", "log"),
    ("network", "network"),
    ("evolution", "evolution"),
    ("memory", "memory"),
    ("strategy", "strategy"),
    ("analysis", "analysis"),
    ("ui", "ui"),
    ("parser", "parser"),
    ("prompt", "prompt"),
    ("git-commit-profile", "git.commit_message_profile"),
    ("git-commit-prompt", "git.commit_message_prompt"),
    ("debug", "debug"),
    ("pet", "pet"),
]


def _humanize_token(token: str) -> str:
    cleaned = str(token or "").strip()
    if not cleaned:
        return ""
    return " ".join(part.upper() if part.isupper() else part.capitalize() for part in cleaned.split("_") if part)


def localize_label(path: str, fallback: str, lang: str) -> str:
    exact = FIELD_LABELS.get(lang, {}).get(path)
    if exact:
        return exact
    parts = [part for part in str(path or "").split(".") if part]
    suffix_map = FIELD_SUFFIX_LABELS.get(lang, {})
    for token_count in (2, 1):
        if len(parts) >= token_count:
            suffix = ".".join(parts[-token_count:])
            mapped = suffix_map.get(suffix)
            if mapped:
                return mapped
    token = str(fallback or "").strip() or str(path or "").split(".")[-1]
    parts = [part for part in token.split("_") if part]
    if not parts:
        return token
    return " ".join(_humanize_token(part) for part in parts)


def localize_section_label(path: str, fallback: str, lang: str) -> str:
    exact = SECTION_LABELS.get(lang, {}).get(path)
    if exact:
        return exact
    return localize_label(path, fallback, lang)


def field_hint(path: str, lang: str) -> str:
    return FIELD_HINTS.get(lang, {}).get(path, "")


def localize_badge(label: str, lang: str) -> str:
    return BADGE_LABELS.get(lang, {}).get(label, label)


def _is_secret_path(path: str) -> bool:
    return str(path or "").split(".")[-1] == "api_key"


def _field_options(path: str, lang: str) -> list[dict[str, str]]:
    if path == "ui.language":
        return [
            {"value": "zh", "label": "中文" if lang == "zh" else "Chinese"},
            {"value": "en", "label": "English"},
        ]
    if path == "runtime.profile":
        return [{"value": value, "label": value} for value in RUNTIME_PROFILE_OPTIONS]
    if path == "workbench.window_mode":
        labels = {
            "zh": {
                "windowed": "窗口化",
                "fullscreen": "沉浸全屏",
            },
            "en": {
                "windowed": "Windowed",
                "fullscreen": "Immersive fullscreen",
            },
        }
        return [{"value": value, "label": labels.get(lang, labels["en"]).get(value, value)} for value in WORKBENCH_WINDOW_MODE_OPTIONS]
    if path == "avatar.preset":
        return [{"value": value, "label": value} for value in AVATAR_PRESET_OPTIONS]
    if path == "user_profile.avatar_preset":
        return [{"value": value, "label": value} for value in USER_AVATAR_PRESET_OPTIONS]
    if path in {"agent.default_mode", "agent.modes.default_shell_mode", "agent.modes.default_headless_mode"}:
        return [{"value": value, "label": value} for value in AGENT_MODE_OPTIONS]
    if path == "evolution.chat_dataset.segmentation_strategy":
        return [{"value": value, "label": value} for value in SEGMENTATION_STRATEGY_OPTIONS]
    return []


def _field_options_for_config(path: str, public_config: dict[str, Any], lang: str) -> list[dict[str, str]]:
    if path == "git.commit_message_profile":
        profiles = public_config.get("llm", {}).get("profiles", {}) if isinstance(public_config.get("llm", {}), dict) else {}
        if isinstance(profiles, dict):
            return [{"value": str(profile_id), "label": str(profile_id)} for profile_id in profiles.keys()]
        return [{"value": "primary", "label": "primary"}]
    if path == "tools.image2.default_model_ref":
        llm = public_config.get("llm", {})
        model_library = llm.get("model_library", {}) if isinstance(llm, dict) else {}
        options = [{"value": "", "label": "未设置" if lang == "zh" else "Not set"}]
        if isinstance(model_library, dict):
            for model_id, item in model_library.items():
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("model") or model_id)
                options.append({"value": str(model_id), "label": label})
        return options
    return _field_options(path, lang)


def _field_kind(path: str, value: Any, options: list[dict[str, str]] | None = None) -> tuple[str, str]:
    if path == "user_profile.avatar_image_path":
        return "image", "Image"
    if path in {"git.commit_message_prompt", "user_profile.bio"}:
        return "multiline", "Multiline"
    if isinstance(value, bool):
        return "boolean", "Toggle"
    if options:
        return "select", "Option"
    if isinstance(value, int) and not isinstance(value, bool):
        if any(token in path for token in ("timeout", "interval", "runtime")):
            return "number", "Seconds"
        if any(token in path for token in ("tokens", "token", "context_window")):
            return "number", "Token"
        return "number", "Number"
    if isinstance(value, float):
        return "number", "Number"
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "string_list", "List"
    if isinstance(value, list):
        return "json", "JSON"
    if _is_secret_path(path):
        return "secret", "Secret"
    if any(token in path for token in ("url", "api_base", "base_url")):
        return "url", "URL"
    path_tokens = set(str(path or "").replace("-", "_").replace(".", "_").split("_"))
    if path_tokens.intersection({"path", "workspace", "directory", "directories", "file", "log"}):
        return "path", "Path"
    return "text", "Text"


def _lookup_path_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in [token for token in str(path or "").split(".") if token]:
        if isinstance(current, dict):
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            current = current[int(part)]
            continue
        raise KeyError(path)
    return current


def _count_leaf_fields(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count_leaf_fields(item) for item in value.values())
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return sum(_count_leaf_fields(item) for item in value)
    return 1


def _walk_editor_meta(value: Any, path: str, lang: str, into: dict[str, dict[str, Any]], public_config: dict[str, Any]) -> None:
    label = localize_section_label(path, path.split(".")[-1] if path else "", lang)
    hint = field_hint(path, lang)
    if isinstance(value, dict):
        into[path] = {
            "path": path,
            "label": label,
            "hint": hint,
            "kind": "object",
            "badge": localize_badge("Group", lang),
            "options": [],
        }
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            _walk_editor_meta(child, child_path, lang, into, public_config)
        return
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        into[path] = {
            "path": path,
            "label": label,
            "hint": hint,
            "kind": "object_list",
            "badge": localize_badge("List", lang),
            "options": [],
        }
        for index, child in enumerate(value):
            child_path = f"{path}.{index}"
            _walk_editor_meta(child, child_path, lang, into, public_config)
        return
    options = _field_options_for_config(path, public_config, lang)
    kind, badge = _field_kind(path, value, options)
    into[path] = {
        "path": path,
        "label": localize_label(path, path.split(".")[-1] if path else "", lang),
        "hint": hint,
        "kind": kind,
        "badge": localize_badge(badge, lang),
        "options": options,
    }


def build_editor_meta(public_config: dict[str, Any], lang: str) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for _, path in EDITOR_SECTION_SPECS:
        try:
            section_value = _lookup_path_value(public_config, path)
        except KeyError:
            continue
        _walk_editor_meta(copy.deepcopy(section_value), path, lang, meta, public_config)
    return meta


def build_editor_sections(public_config: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for section_id, path in EDITOR_SECTION_SPECS:
        try:
            value = _lookup_path_value(public_config, path)
        except KeyError:
            continue
        title = localize_section_label(path, path.split(".")[-1], lang)
        sections.append(
            {
                "id": section_id,
                "path": path,
                "title": title,
                "summary": field_hint(path, lang)
                or (
                    "结构化编辑并确认这个配置分区，再统一应用。"
                    if lang == "zh"
                    else "Edit and confirm this config block before the global apply step."
                ),
                "fieldCount": _count_leaf_fields(value),
            }
        )
    return sections
