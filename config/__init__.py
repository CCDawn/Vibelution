"""
配置模块 (config/)

提供现代化的配置管理，基于 Pydantic v2 实现。
支持从 TOML 文件、环境变量加载配置，提供严格的类型校验。

模块结构：
- models: Pydantic 数据模型定义
- providers: LLM 模型预设注册表
- settings: 配置加载与单例管理

快速开始：
    from config import get_settings, use_model

    # 获取配置
    settings = get_settings()
    print(settings.config.llm.model_name)

    # 切换模型
    use_model("gpt-4")

    # 从 providers 获取信息
    from config import list_models, show_model_info
    print(show_model_info("gpt-4"))
"""

import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

# ============================================================================
# 导出 Pydantic 数据模型
# ============================================================================

from .models import (
    # 数据模型
    LLMConfig,
    LLMDiscoveryConfig,
    LocalLLMConfig,
    AgentConfig,
    ContextCompressionConfig,
    ToolConfig,
    LogConfig,
    NetworkConfig,
    AppConfig,
    # 子配置
    CompressionLevelsConfig,
    CompressionSummaryCharsConfig,
    CompressionPreservationConfig,
    ToolsFileConfig,
    ToolsShellConfig,
    ToolsSearchConfig,
    ToolsWebConfig,
    SecurityConfig,
    EvolutionConfig,
    MemoryConfig,
    StrategyConfig,
    AnalysisConfig,
    UIConfig,
    ParserConfig,
    DebugConfig,
    CompatConfig,
    AvatarConfig,
    PromptConfig,
    SectionConfig,
    # 宠物系统配置
    PetConfig,
    GeneConfig,
    HeartConfig,
    DreamConfig,
    PersonalityConfig,
    HungerConfig,
    DiaryConfig,
    SocialConfig,
    HealthConfig,
    SkinConfig,
    SoundConfig,
)

# ============================================================================
# 导出模型预设和工具函数
# ============================================================================

from .providers import (
    # 模型预设
    ModelPreset,
    MODEL_PRESETS,
    PROVIDER_METADATA,
    MODEL_ALIASES,
    # 工具函数
    list_models,
    list_models_by_provider,
    get_model_preset,
    get_provider_models,
    show_model_info,
    resolve_model_alias,
)

# ============================================================================
# 导出配置加载和单例管理
# ============================================================================

from .settings import (
    # 核心类
    AppConfig,
    ConfigLoader,
    Settings,
    # 单例函数
    get_settings,
    get_config,
    # 便捷函数
    use_model,
    switch_model,
    # 便捷配置访问
    get_llm_config,
    get_local_llm_config,
    get_agent_config,
    get_compression_config,
    get_tools_config,
    get_log_config,
    get_network_config,
    get_security_config,
    get_evolution_config,
    get_memory_config,
    get_strategy_config,
    get_ui_config,
    get_parser_config,
    get_prompt_config,
    get_debug_config,
    get_pet_config,
    get_pet_gene_config,
    get_pet_heart_config,
    get_pet_dream_config,
    get_pet_personality_config,
    get_pet_hunger_config,
    get_pet_diary_config,
    get_pet_social_config,
    get_pet_health_config,
    get_pet_skin_config,
    get_pet_sound_config,
)

# ============================================================================
# 向后兼容：保持 MODEL_REGISTRY 名称（原代码中的名称）
# ============================================================================

MODEL_REGISTRY = MODEL_PRESETS


# ============================================================================
# 向后兼容：Config 类
# ============================================================================

class Config(AppConfig):
    """
    统一配置管理类（向后兼容）

    此类继承自新的 AppConfig，提供与旧版 Config 完全兼容的接口。

    Example:
        # 方式1: 使用预定义模型
        config = use_model("gpt-4")
        config = use_model("claude-3.5")
        config = use_model("deepseek")

        # 方式2: 从 config.toml 读取
        config = Config()

        # 方式3: 从字典创建
        config = Config.from_dict({'llm.model_name': 'gpt-4'})
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        env_prefix: str = "AGENT_",
        **kwargs
    ) -> None:
        """
        初始化配置

        Args:
            config_path: 配置文件路径
            env_prefix: 环境变量前缀
            **kwargs: 其他配置参数（最高优先级，优先级：kwargs > TOML > 环境变量 > 默认值）
        """
        # 使用 Settings 加载配置（kwargs 最高优先级）
        settings = Settings(config_path, **kwargs)
        loaded_config = settings.config

        # 调用父类初始化
        super().__init__(
            llm=loaded_config.llm,
            llm_discovery=loaded_config.llm_discovery,
            llm_local=loaded_config.llm_local,
            avatar=loaded_config.avatar,
            agent=loaded_config.agent,
            context_compression=loaded_config.context_compression,
            tools=loaded_config.tools,
            security=loaded_config.security,
            log=loaded_config.log,
            network=loaded_config.network,
            evolution=loaded_config.evolution,
            memory=loaded_config.memory,
            strategy=loaded_config.strategy,
            analysis=loaded_config.analysis,
            ui=loaded_config.ui,
            debug=loaded_config.debug,
            compat=loaded_config.compat,
        )

        # 存储配置路径和环境变量前缀
        object.__setattr__(self, '_config_path', config_path)
        object.__setattr__(self, '_env_prefix', env_prefix)

        # 应用 kwargs 到 self（最高优先级，覆盖 TOML 和环境变量）
        for key, value in kwargs.items():
            if value is None:
                continue
            # 支持两种格式：
            # 1. 点号格式：'llm.model_name'（来自字典）
            # 2. 双下划线格式：'llm__model_name' -> 'llm.model_name'（Python kwargs 不支持点号）
            # 3. 单下划线格式：'llm_model_name' -> 'llm.model_name'（section 内不能有单下划线）
            # 规则：双下划线变点号，第一个单下划线变点号（section 和 setting 之间的分隔）
            normalized_key = key.replace('__', '.')
            if '.' not in normalized_key and '_' in normalized_key:
                # 只有没有点号且有下划线时，才将第一个下划线替换为点号
                idx = normalized_key.index('_')
                normalized_key = normalized_key[:idx] + '.' + normalized_key[idx+1:]
            if '.' in normalized_key:
                section, setting = normalized_key.split('.', 1)
                if hasattr(self, section):
                    sub_config = getattr(self, section)
                    if hasattr(sub_config, setting):
                        setattr(sub_config, setting, value)

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'Config':
        """
        从字典创建配置

        Args:
            config_dict: 配置字典，支持点号分隔的键名

        Returns:
            Config 实例
        """
        config = cls()
        for key, value in config_dict.items():
            keys = key.split('.')
            if len(keys) == 2:
                section, setting = keys
                if hasattr(config, section):
                    section_obj = getattr(config, section)
                    if hasattr(section_obj, setting):
                        setattr(section_obj, setting, value)
        return config

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
            "local": "LOCAL_API_KEY",
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
        os.environ['OPENAI_API_KEY'] = api_key

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典（向后兼容）

        Returns:
            配置字典
        """
        # 使用 Pydantic v2 的 model_dump()
        data = self.model_dump()
        return {
            'llm': {
                'provider': data['llm']['provider'],
                'model_name': data['llm']['model_name'],
                'temperature': data['llm']['temperature'],
                'max_tokens': data['llm']['max_tokens'],
                'api_base': data['llm']['api_base'],
                'api_timeout': data['llm']['api_timeout'],
            },
            'agent': {
                'name': data['agent']['name'],
                'awake_interval': data['agent']['awake_interval'],
                'max_iterations': data['agent']['max_iterations'],
                'auto_backup': data['agent']['auto_backup'],
            },
            'log': {
                'level': data['log']['level'],
            },
        }


# ============================================================================
# 向后兼容：全局配置
# ============================================================================

_default_config: Optional[Config] = None


def get_config_legacy(config_path: Optional[str] = None) -> Config:
    """
    获取全局默认配置

    Args:
        config_path: 配置文件路径

    Returns:
        Config 实例
    """
    global _default_config
    if _default_config is None or config_path is not None:
        _default_config = Config(config_path=config_path)
    return _default_config


# ============================================================================
# __getattr__ 支持（Python 3.7+ 模块级懒加载）
# ============================================================================

def __getattr__(name: str):
    """
    模块级属性懒加载

    支持:
        import config
        config.Config          -> Config 类
        config.use_model()     -> use_model 函数
        config.list_models()   -> list_models 函数
    """
    if name == 'Config':
        return Config
    elif name == 'get_config':
        return get_config_legacy
    elif name in ('use_model', 'switch_model', 'list_models', 'show_model_info',
                  'MODEL_REGISTRY', 'get_model_preset'):
        return globals()[name]
    raise AttributeError(f"module 'config' has no attribute '{name}'")


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("可用模型列表")
    print("=" * 60)
    print()

    # 按提供商分组显示
    providers: Dict[str, List] = {}
    for model_id, preset in MODEL_REGISTRY.items():
        if preset.provider not in providers:
            providers[preset.provider] = []
        providers[preset.provider].append({
            "id": model_id,
            "name": preset.name,
            "description": preset.description,
        })

    for provider, models in providers.items():
        print(f"[{provider.upper()}]")
        for model in models:
            print(f"  {model['id']:25s} - {model['name']}")
            print(f"  {'':25s}   {model['description']}")
        print()

    print("=" * 60)
    print("使用方法")
    print("=" * 60)
    print()
    print("# 方式1: 使用预定义模型")
    print("from config import use_model")
    print("config = use_model('gpt-4')")
    print()
    print("# 方式2: 从 config.toml 读取")
    print("from config import Config")
    print("config = Config()")
    print()
    print("# 方式3: 从字典创建")
    print("config = Config.from_dict({'llm.model_name': 'gpt-4'})")
    print()
    print("# 查看模型详情")
    print("from config import show_model_info")
    print("print(show_model_info('gpt-4'))")
    print()
    print("=" * 60)
    print("新版 API (推荐)")
    print("=" * 60)
    print()
    print("from config import get_settings")
    print()
    print("settings = get_settings()")
    print("print(settings.config.llm.model_name)")
    print()
    print("settings.use_model('gpt-4')")


# ============================================================================
# 导出列表
# ============================================================================

__all__ = [
    # 主配置类
    "AppConfig",
    "Config",
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
    # 工具配置
    "ToolConfig",
    "ToolsFileConfig",
    "ToolsShellConfig",
    "ToolsSearchConfig",
    "ToolsWebConfig",
    # 其他配置
    "LogConfig",
    "NetworkConfig",
    "SecurityConfig",
    "EvolutionConfig",
    "MemoryConfig",
    "StrategyConfig",
    "AnalysisConfig",
    "UIConfig",
    "DebugConfig",
    "CompatConfig",
    "AvatarConfig",
    "PromptConfig",
    "SectionConfig",
    # 提供商
    "ModelPreset",
    "MODEL_PRESETS",
    "MODEL_REGISTRY",
    "PROVIDER_METADATA",
    "MODEL_ALIASES",
    # 核心类
    "ConfigLoader",
    "Settings",
    # 单例和便捷函数
    "get_settings",
    "get_config",
    "use_model",
    "switch_model",
    "get_config_legacy",
    # 便捷配置访问函数
    "get_llm_config",
    "get_local_llm_config",
    "get_agent_config",
    "get_compression_config",
    "get_tools_config",
    "get_log_config",
    "get_network_config",
    "get_security_config",
    "get_evolution_config",
    "get_memory_config",
    "get_strategy_config",
    "get_ui_config",
    "get_prompt_config",
    "get_debug_config",
    # 工具函数
    "list_models",
    "list_models_by_provider",
    "get_model_preset",
    "get_provider_models",
    "show_model_info",
    "resolve_model_alias",
    # LLM Provider 适配器
    "MiniMaxOpenAIAdapter",
    "MiniMaxResponse",
]
