"""
Pydantic 数据模型定义

使用 Pydantic v2 定义所有配置项的数据模型，提供严格的类型校验和验证逻辑。

所有配置支持：
1. 从 config.toml 加载
2. 从环境变量覆盖
3. 从字典创建
4. 程序化修改
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    computed_field,
)
from pydantic import ConfigDict


# ============================================================================
# LLM 配置
# ============================================================================

class LLMConfig(BaseModel):
    """
    大语言模型 (LLM) 配置

    Attributes:
        provider: 模型提供商 (openai, anthropic, deepseek, aliyun 等)
        model_name: 具体模型名称
        api_key: API 密钥（可从配置文件读取）
        api_base: API 端点 URL
        temperature: 采样温度，控制输出的随机性 (0.0-2.0)
        max_tokens: 最大输出 token 数
        api_timeout: API 请求超时时间（秒）
        connect_timeout: 连接超时时间（秒）
        discovery: 模型动态发现配置
    """
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(
        default="aliyun",
        description="LLM 提供商: openai, anthropic, deepseek, aliyun, google, ollama, local 等"
    )
    model_name: str = Field(
        default="qwen-plus",
        description="具体模型名称，如 gpt-4, claude-3-5-sonnet-20241022, deepseek-chat"
    )
    api_key: str = Field(
        default="",
        description="API 密钥，可从环境变量获取"
    )
    api_base: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="API 端点 URL"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="采样温度 (0.0-2.0)，越低越确定性，越高越随机"
    )
    max_tokens: int = Field(
        default=4096,
        gt=0,
        description="最大输出 token 数（会被运行时动态发现覆盖）"
    )
    api_timeout: int = Field(
        default=60,
        gt=0,
        description="API 请求超时时间（秒）"
    )
    connect_timeout: int = Field(
        default=30,
        gt=0,
        description="连接超时时间（秒）"
    )

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """验证提供商名称"""
        valid_providers = [
            "openai", "anthropic", "deepseek", "aliyun",
            "google", "zhipu", "ollama", "siliconflow", "groq", "minimax", "local"
        ]
        if v.lower() not in valid_providers:
            pass
        return v.lower()

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """确保温度在有效范围内"""
        if not 0.0 <= v <= 2.0:
            raise ValueError(f"Temperature must be between 0.0 and 2.0, got {v}")
        return round(v, 2)


class LLMDiscoveryConfig(BaseModel):
    """LLM 动态发现配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用运行时模型发现"
    )
    timeout: int = Field(
        default=30,
        gt=0,
        description="发现请求超时（秒）"
    )
    fallback_max_tokens: Optional[int] = Field(
        default=None,
        description="发现失败时使用的 max_tokens"
    )
    fallback_max_token_limit: Optional[int] = Field(
        default=None,
        description="发现失败时使用的 max_token_limit"
    )
    auto_adjust: bool = Field(
        default=True,
        description="是否自动调整压缩阈值"
    )
    output_reserve_ratio: float = Field(
        default=0.125,
        ge=0.1,
        le=0.5,
        description="预留输出 tokens 比例"
    )


class LocalLLMConfig(BaseModel):
    """本地部署 LLM 配置（当 provider = "local" 时生效）"""
    model_config = ConfigDict(extra="ignore")

    url: str = Field(
        default="http://localhost:11434/v1",
        description="本地服务 URL（Ollama, LM Studio, vLLM 等）"
    )
    model: str = Field(
        default="qwen2.5:7b",
        description="本地模型名称"
    )
    require_api_key: bool = Field(
        default=False,
        description="是否需要 API Key"
    )
    api_key: str = Field(
        default="",
        description="本地 API Key（如果需要）"
    )
    streaming: bool = Field(
        default=True,
        description="是否启用流式响应"
    )
    context_window: int = Field(
        default=8192,
        gt=0,
        description="上下文窗口大小（自动发现失败时使用）"
    )
    auto_detect_model: bool = Field(
        default=True,
        description="是否自动检测可用模型"
    )
    model_refresh_interval: int = Field(
        default=300,
        gt=0,
        description="模型列表刷新间隔（秒）"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="连接失败重试次数"
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0,
        description="重试间隔（秒）"
    )


# ============================================================================
# Agent 行为配置
# ============================================================================

class AgentConfig(BaseModel):
    """
    Agent 行为配置

    Attributes:
        name: Agent 实例名称
        workspace: 工作区目录路径
        awake_interval: 苏醒间隔（秒），Agent 定期检查是否有任务
        max_iterations: 单次苏醒的最大工具调用次数
        max_runtime: 最大运行时间（秒），0 表示无限制
        auto_backup: 是否启用自动备份
        backup_interval: 自动备份间隔（秒）
        auto_restart_threshold: 自动重启阈值（错误次数），0 表示禁用
        exploration_mode: 是否启用探索模式
    """
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        default="SelfEvolvingAgent",
        description="Agent 名称"
    )
    workspace: str = Field(
        default="workspace",
        description="工作区目录（相对于项目根目录）"
    )
    awake_interval: int = Field(
        default=60,
        gt=0,
        description="苏醒间隔（秒）"
    )
    max_iterations: int = Field(
        default=10,
        gt=0,
        description="单次苏醒的最大工具调用次数"
    )
    max_runtime: int = Field(
        default=0,
        ge=0,
        description="最大运行时间（秒），0 表示无限制"
    )
    auto_backup: bool = Field(
        default=True,
        description="是否启用自动备份"
    )
    backup_interval: int = Field(
        default=300,
        gt=0,
        description="自动备份间隔（秒）"
    )
    auto_restart_threshold: int = Field(
        default=0,
        ge=0,
        description="自动重启阈值，0 表示禁用"
    )
    exploration_mode: bool = Field(
        default=False,
        description="是否启用探索模式"
    )

    @field_validator("awake_interval", "max_iterations", "backup_interval")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """验证正整数"""
        if v <= 0:
            raise ValueError(f"Value must be positive, got {v}")
        return v


# ============================================================================
# 上下文压缩配置
# ============================================================================

class CompressionLevelsConfig(BaseModel):
    """压缩级别阈值配置"""
    model_config = ConfigDict(extra="ignore")

    light: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="轻度压缩阈值（相对于 max_token_limit）"
    )
    standard: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="标准压缩阈值"
    )
    deep: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="深度压缩阈值"
    )
    emergency: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="紧急压缩阈值"
    )


class CompressionSummaryCharsConfig(BaseModel):
    """各压缩级别摘要字数配置"""
    model_config = ConfigDict(extra="ignore")

    light: int = Field(
        default=500,
        ge=0,
        description="轻度压缩摘要字数"
    )
    standard: int = Field(
        default=1000,
        ge=0,
        description="标准压缩摘要字数"
    )
    deep: int = Field(
        default=2000,
        ge=0,
        description="深度压缩摘要字数"
    )
    emergency: int = Field(
        default=3000,
        ge=0,
        description="紧急压缩摘要字数"
    )


class CompressionPreservationConfig(BaseModel):
    """智能保留策略配置"""
    model_config = ConfigDict(extra="ignore")

    keep_ai_messages: int = Field(
        default=5,
        ge=0,
        description="保留最近 AI 消息数"
    )
    keep_tool_results: bool = Field(
        default=True,
        description="保留工具调用结果"
    )
    preserve_errors: bool = Field(
        default=True,
        description="保留错误信息"
    )
    extract_key_decisions: bool = Field(
        default=True,
        description="提取关键决策"
    )


class ContextCompressionConfig(BaseModel):
    """
    运行时上下文压缩配置

    Attributes:
        enabled: 是否启用压缩
        max_token_limit: Token 阈值，超过此值触发压缩
        keep_recent_steps: 保留最近的工具调用次数
        summary_max_chars: 压缩摘要的最大字符数
        compression_model: 用于压缩的模型名称
        compression_temperature: 压缩用模型温度
        max_compressions_per_session: 每会话最大压缩次数
        effectiveness_threshold: 压缩效率阈值
    """
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用上下文压缩"
    )
    max_token_limit: int = Field(
        default=16000,
        gt=0,
        description="Token 阈值，超过此值触发压缩"
    )
    keep_recent_steps: int = Field(
        default=2,
        ge=0,
        description="保留最近的工具调用次数"
    )
    summary_max_chars: int = Field(
        default=200,
        gt=0,
        description="压缩摘要的最大字符数"
    )
    compression_model: str = Field(
        default="qwen-turbo",
        description="用于压缩的轻量模型"
    )
    compression_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="压缩用模型温度"
    )
    max_compressions_per_session: int = Field(
        default=20,
        ge=0,
        description="每会话最大压缩次数"
    )
    effectiveness_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="压缩效率阈值"
    )
    levels: CompressionLevelsConfig = Field(
        default_factory=CompressionLevelsConfig,
        description="压缩级别阈值配置"
    )
    summary_chars: CompressionSummaryCharsConfig = Field(
        default_factory=CompressionSummaryCharsConfig,
        description="各压缩级别摘要字数配置"
    )
    preservation: CompressionPreservationConfig = Field(
        default_factory=CompressionPreservationConfig,
        description="智能保留策略配置"
    )

    @model_validator(mode="after")
    def validate_limits(self) -> "ContextCompressionConfig":
        """验证限制参数"""
        if self.keep_recent_steps > 10:
            raise ValueError("keep_recent_steps should not exceed 10")
        if self.summary_max_chars > 1000:
            raise ValueError("summary_max_chars should not exceed 1000")
        return self


# ============================================================================
# 形象配置
# ============================================================================

class AvatarConfig(BaseModel):
    """ASCII 形象配置"""
    model_config = ConfigDict(extra="ignore")

    preset: str = Field(
        default="lobster",
        description="预设形象: lobster(龙虾), shrimp(小虾米), crab(小螃蟹), cat(猫猫), chick(小鸡)"
    )


# ============================================================================
# 文件操作配置
# ============================================================================

class ToolsFileConfig(BaseModel):
    """文件操作工具配置"""
    model_config = ConfigDict(extra="ignore")

    edit_enabled: bool = Field(
        default=True,
        description="是否启用文件编辑"
    )
    create_enabled: bool = Field(
        default=True,
        description="是否启用文件创建"
    )
    syntax_check_enabled: bool = Field(
        default=True,
        description="是否启用语法检查"
    )
    max_read_lines: int = Field(
        default=0,
        ge=0,
        description="单次读取最大行数（0 表示无限制）"
    )
    max_read_chars: int = Field(
        default=0,
        ge=0,
        description="单次读取最大字符数（0 表示无限制）"
    )
    encoding_priority: List[str] = Field(
        default_factory=lambda: ["utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"],
        description="文件编码自动检测顺序"
    )
    editable_extensions: List[str] = Field(
        default_factory=lambda: [
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".kt", ".go", ".rs",
            ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".html", ".css", ".scss",
            ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt",
            ".sh", ".sql", ".xml", ".svg"
        ],
        description="允许编辑的文件扩展名"
    )


# ============================================================================
# Shell 命令配置
# ============================================================================

class ToolsShellConfig(BaseModel):
    """Shell 命令工具配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用 Shell 执行"
    )
    default_timeout: int = Field(
        default=60,
        gt=0,
        description="默认超时时间（秒）"
    )
    max_output_length: int = Field(
        default=10000,
        gt=0,
        description="最大输出长度（字符）"
    )
    max_file_size: int = Field(
        default=10485760,
        gt=0,
        description="最大文件大小（字节）"
    )
    safety_check: bool = Field(
        default=True,
        description="是否启用安全检查"
    )
    dangerous_pattern_check: bool = Field(
        default=True,
        description="危险命令黑名单检测"
    )
    allowed_shells: List[str] = Field(
        default_factory=lambda: ["powershell", "cmd", "bash"],
        description="允许的 Shell 类型"
    )


# ============================================================================
# 搜索工具配置
# ============================================================================

class ToolsSearchConfig(BaseModel):
    """搜索工具配置"""
    model_config = ConfigDict(extra="ignore")

    max_file_size: int = Field(
        default=10485760,
        gt=0,
        description="搜索最大文件大小（字节）"
    )
    max_matches_per_file: int = Field(
        default=100,
        gt=0,
        description="每个文件最大匹配数"
    )
    max_results: int = Field(
        default=500,
        gt=0,
        description="最大总结果数"
    )
    context_lines: int = Field(
        default=3,
        ge=0,
        description="上下文行数"
    )
    skip_directories: List[str] = Field(
        default_factory=lambda: [
            "__pycache__", ".git", ".svn", ".hg", "node_modules",
            ".venv", "venv", "env", ".env", ".idea", ".vscode",
            "dist", "build", ".tox", ".pytest_cache", ".mypy_cache",
            "site-packages", "egg-info", ".eggs"
        ],
        description="搜索时跳过的目录"
    )
    skip_extensions: List[str] = Field(
        default_factory=lambda: [".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo", ".pyd"],
        description="搜索时跳过的文件扩展名"
    )
    include_extensions: List[str] = Field(
        default_factory=lambda: [
            ".py", ".js", ".ts", ".jsx", ".tsx", ".md", ".json", ".yaml",
            ".yml", ".toml", ".txt", ".html", ".css", ".xml", ".sh", ".bat", ".ps1"
        ],
        description="搜索时包含的文件扩展名"
    )


# ============================================================================
# 网络工具配置
# ============================================================================

class ToolsWebConfig(BaseModel):
    """网络工具配置"""
    model_config = ConfigDict(extra="ignore")

    search_enabled: bool = Field(
        default=True,
        description="是否启用网络搜索"
    )
    max_search_results: int = Field(
        default=10,
        gt=0,
        description="搜索结果数量"
    )
    search_timeout: int = Field(
        default=30,
        gt=0,
        description="搜索超时（秒）"
    )


# ============================================================================
# 工具配置
# ============================================================================

class ToolConfig(BaseModel):
    """工具模块配置"""
    model_config = ConfigDict(extra="ignore")

    web_search_enabled: bool = Field(
        default=True,
        description="是否启用网络搜索（向后兼容）"
    )
    file_edit_enabled: bool = Field(
        default=True,
        description="是否启用文件编辑（向后兼容）"
    )
    syntax_check_enabled: bool = Field(
        default=True,
        description="是否启用语法检查（向后兼容）"
    )
    restart_enabled: bool = Field(
        default=True,
        description="是否允许 Agent 自我重启"
    )
    allowed_directories: List[str] = Field(
        default_factory=list,
        description="允许访问的目录列表"
    )
    forbidden_patterns: List[str] = Field(
        default_factory=lambda: [
            ".env", ".password", ".secret", ".key",
            "id_rsa", "credentials.json"
        ],
        description="禁止访问的文件模式"
    )
    file: ToolsFileConfig = Field(
        default_factory=ToolsFileConfig,
        description="文件操作配置"
    )
    shell: ToolsShellConfig = Field(
        default_factory=ToolsShellConfig,
        description="Shell 命令配置"
    )
    search: ToolsSearchConfig = Field(
        default_factory=ToolsSearchConfig,
        description="搜索工具配置"
    )
    web: ToolsWebConfig = Field(
        default_factory=ToolsWebConfig,
        description="网络工具配置"
    )

    @model_validator(mode="after")
    def setup_directories(self) -> "ToolConfig":
        """自动设置默认允许目录"""
        if not self.allowed_directories:
            project_root = Path(__file__).parent.parent.resolve()
            self.allowed_directories = [
                str(project_root),
                str(project_root / "tools"),
                str(Path.cwd()),
                str(Path.home()),
            ]
        return self


# ============================================================================
# 安全配置
# ============================================================================

class SecurityConfig(BaseModel):
    """安全配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用安全验证"
    )
    allowed_directories: List[str] = Field(
        default_factory=list,
        description="允许访问的根目录"
    )
    forbidden_patterns: List[str] = Field(
        default_factory=lambda: [
            ".env", ".password", ".secret", ".key",
            "id_rsa", "credentials.json"
        ],
        description="禁止访问的文件模式"
    )
    forbidden_delete_patterns: List[str] = Field(
        default_factory=lambda: [
            ".env", ".password", ".secret", ".key", "id_rsa", "credentials.json",
            "config.py", "config.toml", ".git", "restarter.py", "agent.py"
        ],
        description="禁止删除的文件/目录"
    )
    dangerous_commands: List[str] = Field(
        default_factory=lambda: [
            "rm -rf /", "rm -rf /*", "mkfs", "dd if=/dev/zero of=/dev/sda",
            "format", "del /f /s /q", "rmdir /s /q", "rm -rf",
            "cipher /w:", "shutdown", "sysprep", ":(){ :|:& };:"
        ],
        description="危险命令黑名单"
    )


# ============================================================================
# 日志配置
# ============================================================================

class LogThirdPartyConfig(BaseModel):
    """第三方库日志级别配置"""
    model_config = ConfigDict(extra="ignore")

    httpx: str = Field(default="WARNING")
    httpcore: str = Field(default="WARNING")
    langchain: str = Field(default="WARNING")
    openai: str = Field(default="WARNING")
    anthropic: str = Field(default="WARNING")
    urllib3: str = Field(default="WARNING")
    litellm: str = Field(default="WARNING")
    rich: str = Field(default="WARNING")


class LogConfig(BaseModel):
    """日志系统配置"""
    model_config = ConfigDict(extra="ignore")

    level: str = Field(
        default="INFO",
        description="日志级别"
    )
    format: str = Field(
        default="%(asctime)s | %(levelname)-8s | %(message)s",
        description="日志格式"
    )
    date_format: str = Field(
        default="%Y-%m-%d %H:%M:%S",
        description="日期时间格式"
    )
    file_enabled: bool = Field(
        default=False,
        description="是否写入文件"
    )
    file_path: str = Field(
        default="logs/agent.log",
        description="日志文件路径"
    )
    max_file_size: int = Field(
        default=10485760,
        ge=0,
        description="最大日志文件大小（字节）"
    )
    backup_count: int = Field(
        default=5,
        ge=0,
        description="保留的日志文件数量"
    )
    detailed_traceback: bool = Field(
        default=False,
        description="是否启用详细错误堆栈"
    )
    third_party: LogThirdPartyConfig = Field(
        default_factory=LogThirdPartyConfig,
        description="第三方库日志级别"
    )

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """验证日志级别"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return upper


# ============================================================================
# 网络配置
# ============================================================================

class NetworkConfig(BaseModel):
    """网络请求配置"""
    model_config = ConfigDict(extra="ignore")

    timeout: int = Field(
        default=30,
        gt=0,
        description="请求超时时间（秒）"
    )
    user_agent: str = Field(
        default="Mozilla/5.0 (compatible; SelfEvolvingAgent/1.0)",
        description="HTTP User-Agent"
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="最大重试次数"
    )
    retry_delay: float = Field(
        default=1.0,
        ge=0,
        description="重试延迟（秒）"
    )
    verify_ssl: bool = Field(
        default=True,
        description="是否验证 SSL 证书"
    )


# ============================================================================
# 进化引擎配置
# ============================================================================

class EvolutionConfig(BaseModel):
    """进化引擎配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description="是否启用自动进化"
    )
    config_path: str = Field(
        default="workspace/evolution_config.json",
        description="进化配置路径"
    )
    archive_dir: str = Field(
        default="workspace/archives",
        description="归档目录"
    )
    backup_dir: str = Field(
        default="backups",
        description="备份目录"
    )
    test_gate_enabled: bool = Field(
        default=True,
        description="是否在重启前运行测试"
    )
    test_gate_timeout: int = Field(
        default=120,
        gt=0,
        description="进化测试超时（秒）"
    )
    test_command: str = Field(
        default="pytest tests/ -v --tb=short -q",
        description="测试命令"
    )


# ============================================================================
# 记忆系统配置
# ============================================================================

class MemoryConfig(BaseModel):
    """记忆系统配置"""
    model_config = ConfigDict(extra="ignore")

    storage_dir: str = Field(
        default="workspace/memory",
        description="记忆存储目录"
    )
    memory_file: str = Field(
        default="memory.json",
        description="记忆文件名称"
    )
    archive_dir: str = Field(
        default="workspace/memory/archives",
        description="归档目录"
    )
    max_entries: int = Field(
        default=1000,
        gt=0,
        description="最大记忆条目数"
    )


# ============================================================================
# 策略系统配置
# ============================================================================

class StrategyConfig(BaseModel):
    """策略系统配置"""
    model_config = ConfigDict(extra="ignore")

    data_dir: str = Field(
        default="workspace/strategy",
        description="策略数据目录"
    )
    exploration_rate: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="探索率"
    )
    learning_enabled: bool = Field(
        default=True,
        description="是否启用策略学习"
    )
    learning_data_path: str = Field(
        default="workspace/strategy/learner_data.json",
        description="学习数据存储路径"
    )


# ============================================================================
# 代码分析配置
# ============================================================================

class AnalysisConfig(BaseModel):
    """代码分析配置"""
    model_config = ConfigDict(extra="ignore")

    data_dir: str = Field(
        default="workspace/analytics",
        description="分析数据目录"
    )
    feedback_dir: str = Field(
        default="workspace/feedback",
        description="反馈数据目录"
    )
    knowledge_graph_path: str = Field(
        default="workspace/knowledge_graph.json",
        description="知识图谱存储路径"
    )
    pattern_library_path: str = Field(
        default="workspace/pattern_library.json",
        description="模式库存储路径"
    )


# ============================================================================
# CLI UI 配置
# ============================================================================

class UIConfig(BaseModel):
    """CLI UI 配置"""
    model_config = ConfigDict(extra="ignore")

    theme: str = Field(
        default="lobster",
        description="主题名称"
    )
    max_log_entries: int = Field(
        default=100,
        gt=0,
        description="日志面板最大条目数"
    )
    refresh_rate: int = Field(
        default=4,
        gt=0,
        description="实时刷新频率"
    )
    show_ascii_art: bool = Field(
        default=True,
        description="是否显示 ASCII Art"
    )
    show_welcome: bool = Field(
        default=True,
        description="是否显示欢迎面板"
    )


# ============================================================================
# 调试配置
# ============================================================================

class DebugConfig(BaseModel):
    """调试配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=False,
        description="是否启用调试模式"
    )
    verbose: bool = Field(
        default=False,
        description="是否打印详细日志"
    )
    trace_llm: bool = Field(
        default=False,
        description="是否跟踪 LLM 调用"
    )
    trace_tools: bool = Field(
        default=False,
        description="是否跟踪工具调用"
    )
    track_token_usage: bool = Field(
        default=True,
        description="Token 使用统计"
    )


# ============================================================================
# 宠物系统配置
# ============================================================================

class PetConfig(BaseModel):
    """宠物系统主配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="是否启用宠物系统")
    name: str = Field(default="虾宝", description="宠物名称")
    auto_save: bool = Field(default=True, description="自动保存")
    save_interval: int = Field(default=60, description="自动保存间隔(秒)")


class GeneConfig(BaseModel):
    """基因系统配置"""
    model_config = ConfigDict(extra="ignore")

    inherit_from_model: bool = Field(default=True, description="从模型继承基因特征")
    context_window_factor: float = Field(default=0.001, description="上下文窗口→寿命因子")


class HeartConfig(BaseModel):
    """心跳系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用心跳可视化")
    active_rate: float = Field(default=2.0, description="活跃时心跳频率(Hz)")
    idle_rate: float = Field(default=0.5, description="空闲时心跳频率(Hz)")
    cooldown_time: int = Field(default=5, description="心跳冷却时间(秒)")


class DreamConfig(BaseModel):
    """梦境系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用梦境系统")
    compression_triggers_dream: bool = Field(default=True, description="压缩时触发梦境")
    dream_duration: int = Field(default=3, description="梦境持续时间(秒)")
    keep_key_memory_ratio: float = Field(default=0.7, description="梦境中保留关键记忆比例")


class PersonalityConfig(BaseModel):
    """性格系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用性格养成")
    learning_window: int = Field(default=100, description="学习窗口(操作次数)")
    trait_change_rate: float = Field(default=0.05, description="性格变化率")


class HungerConfig(BaseModel):
    """饥饿系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用饥饿系统")
    food_per_meal: float = Field(default=0.1, description="每次饭量占上下文比例")
    hunger_decay_rate: float = Field(default=1.0, description="饱食度衰减率")
    mood_decay_rate: float = Field(default=0.5, description="心情衰减率")
    auto_feed_threshold: int = Field(default=1000, description="自动投喂阈值(tokens)")


class DiaryConfig(BaseModel):
    """日记系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用成长日记")
    max_entries: int = Field(default=365, description="最大日记条目数")
    auto_summarize: bool = Field(default=True, description="自动生成摘要")
    sentiment_analysis: bool = Field(default=True, description="情感分析")


class SocialConfig(BaseModel):
    """社交系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用同伴社交")
    track_other_models: bool = Field(default=True, description="跟踪其他模型")
    friendship_gain_rate: float = Field(default=1.0, description="友谊增长速度")
    max_friends: int = Field(default=10, description="最大好友数")


class HealthConfig(BaseModel):
    """健康系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用健康体检")
    check_interval: int = Field(default=30, description="健康检查间隔(秒)")
    response_time_weight: float = Field(default=0.3, description="响应时间权重")
    error_rate_weight: float = Field(default=0.4, description="错误率权重")
    efficiency_weight: float = Field(default=0.3, description="效率权重")


class SkinConfig(BaseModel):
    """装扮系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用装扮系统")
    unlock_by_achievement: bool = Field(default=True, description="通过成就解锁皮肤")


class SoundConfig(BaseModel):
    """声音系统配置"""
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="启用情绪声音")
    volume: float = Field(default=0.5, description="音量(0-1)")
    mood_sounds: bool = Field(default=True, description="心情声音")
    action_sounds: bool = Field(default=True, description="动作声音")


# ============================================================================
# 兼容性配置
# ============================================================================

class CompatConfig(BaseModel):
    """向后兼容配置"""
    model_config = ConfigDict(extra="ignore")

    legacy_api_enabled: bool = Field(
        default=True,
        description="启用旧版 API"
    )
    legacy_config_path: str = Field(
        default="config.py",
        description="旧版配置路径"
    )


# ============================================================================
# 主配置类
# ============================================================================

class AppConfig(BaseModel):
    """
    应用主配置类

    整合所有子配置模块，提供统一的配置管理接口。

    Example:
        # 创建默认配置
        config = AppConfig()

        # 从 TOML 加载
        config = AppConfig.from_toml("config.toml")

        # 访问配置
        config.llm.model_name = "gpt-4"
        print(config.llm.temperature)
    """
    model_config = ConfigDict(extra="ignore")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    llm_discovery: LLMDiscoveryConfig = Field(default_factory=LLMDiscoveryConfig)
    llm_local: LocalLLMConfig = Field(default_factory=LocalLLMConfig)
    avatar: AvatarConfig = Field(default_factory=AvatarConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    context_compression: ContextCompressionConfig = Field(
        default_factory=ContextCompressionConfig
    )
    tools: ToolConfig = Field(default_factory=ToolConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
    compat: CompatConfig = Field(default_factory=CompatConfig)

    # 宠物系统配置
    pet: PetConfig = Field(default_factory=PetConfig)
    pet_gene: GeneConfig = Field(default_factory=GeneConfig)
    pet_heart: HeartConfig = Field(default_factory=HeartConfig)
    pet_dream: DreamConfig = Field(default_factory=DreamConfig)
    pet_personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    pet_hunger: HungerConfig = Field(default_factory=HungerConfig)
    pet_diary: DiaryConfig = Field(default_factory=DiaryConfig)
    pet_social: SocialConfig = Field(default_factory=SocialConfig)
    pet_health: HealthConfig = Field(default_factory=HealthConfig)
    pet_skin: SkinConfig = Field(default_factory=SkinConfig)
    pet_sound: SoundConfig = Field(default_factory=SoundConfig)

    @computed_field
    @property
    def workspace_path(self) -> Path:
        """获取工作区的绝对路径"""
        project_root = Path(__file__).parent.parent
        return project_root / self.agent.workspace

    @computed_field
    @property
    def effective_api_base(self) -> Optional[str]:
        """
        获取实际的 API 端点

        当 provider = "local" 时，使用 llm_local.url；
        否则使用 llm.api_base。
        """
        if self.llm.provider == "local":
            return self.llm_local.url
        return self.llm.api_base

    def model_dump_simple(self) -> dict:
        """
        简化的字典导出（用于日志和调试）

        Returns:
            包含主要配置的字典
        """
        return {
            "llm": {
                "provider": self.llm.provider,
                "model_name": self.llm.model_name,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
            },
            "agent": {
                "name": self.agent.name,
                "awake_interval": self.agent.awake_interval,
                "max_iterations": self.agent.max_iterations,
            },
            "compression": {
                "enabled": self.context_compression.enabled,
                "max_token_limit": self.context_compression.max_token_limit,
            },
            "log_level": self.log.level,
        }

    def get_api_key(self) -> Optional[str]:
        """
        获取 API Key（优先从配置读取，其次环境变量）

        Returns:
            API Key，未设置返回 None
        """
        # 1. 优先从配置读取
        if self.llm.api_key:
            return self.llm.api_key

        # 2. 从环境变量读取
        provider = self.llm.provider
        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "aliyun": "DASHSCOPE_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
            "google": "GOOGLE_API_KEY",
            "siliconflow": "SILICONFLOW_API_KEY",
            "groq": "GROQ_API_KEY",
            "minimax": "MINIMAX_API_KEY",
        }

        env_var = env_var_map.get(provider)
        if env_var:
            return os.environ.get(env_var)

        return None

    def set_api_key(self, api_key: str) -> None:
        """
        设置 API Key

        Args:
            api_key: API 密钥
        """
        self.llm.api_key = api_key

    def __repr__(self) -> str:
        return (
            f"AppConfig(model={self.llm.model_name}, "
            f"provider={self.llm.provider}, "
            f"temperature={self.llm.temperature})"
        )


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    # LLM 配置
    "LLMConfig",
    "LLMDiscoveryConfig",
    "LocalLLMConfig",
    # Agent 配置
    "AgentConfig",
    # 上下文压缩配置
    "ContextCompressionConfig",
    "CompressionLevelsConfig",
    "CompressionSummaryCharsConfig",
    "CompressionPreservationConfig",
    # 形象配置
    "AvatarConfig",
    # 工具配置
    "ToolConfig",
    "ToolsFileConfig",
    "ToolsShellConfig",
    "ToolsSearchConfig",
    "ToolsWebConfig",
    # 安全配置
    "SecurityConfig",
    # 日志配置
    "LogConfig",
    "LogThirdPartyConfig",
    # 网络配置
    "NetworkConfig",
    # 进化引擎配置
    "EvolutionConfig",
    # 记忆系统配置
    "MemoryConfig",
    # 策略系统配置
    "StrategyConfig",
    # 代码分析配置
    "AnalysisConfig",
    # UI 配置
    "UIConfig",
    # 调试配置
    "DebugConfig",
    # 兼容性配置
    "CompatConfig",
    # 主配置类
    "AppConfig",
]
