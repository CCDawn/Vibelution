# 01 · 权威路径与加载

## 默认路径

| 项 | 默认 |
| --- | --- |
| Config home | `%USERPROFILE%\Documents\Vibelution\config` |
| 活跃文件 | `…\config\config.toml` |
| Data home | `%USERPROFILE%\Documents\Vibelution\data` |

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `VIBELUTION_CONFIG_PATH` | 直接指定 `config.toml` 绝对路径 |
| `VIBELUTION_CONFIG_HOME` | 指定配置目录（其下读 `config.toml`） |
| `VIBELUTION_DATA_HOME` | 数据根 |
| `VIBELUTION_ENABLE_USER_ENV_FALLBACK` | Windows 下允许回退读用户级环境变量中的 API Key |

实现：`config/paths.py`。
决策锁定：[ADR 0003](../../adr/0003-operator-config-lives-outside-repo.md)。

## 加载与校验

1. 解析路径 → 读 TOML
2. Pydantic 模型校验（`config/models.py`）
3. Provider / model_ref / credential 规范化
4. 运行时按 **profile** 取 API Key、协议 route、能力

失败时应修 **外部 operator config**，不要在代码里硬编码密钥。

## Agent 操作建议

```text
1. 打印/确认 resolve_config_path()
2. 备份后改 Documents\...\config.toml
3. Launcher 重启或热加载（以产品行为为准）
4. 用诊断/日志确认 profile、provider、protocol
```

## 常见错误

| 现象 | 原因 |
| --- | --- |
| 改了仓库 config 无效果 | 运行时不读仓库根 |
| 密钥「有 env 仍无效」 | 进程未继承；可检查 credential_ref 与 fallback 开关 |
| schema 校验失败 | 字段枚举不合法（见各专节） |
