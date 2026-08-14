# 01 · 权威路径与加载

## 默认路径

| 项 | 默认 |
| --- | --- |
| Config home | `%USERPROFILE%\Documents\Vibelution\config` |
| 活跃文件 | `…\config\config.toml` |
| Project identity | `<project-root>\.vibelution\project.json`（tracked，只含稳定 `projectId`） |
| Project state | `%LOCALAPPDATA%\Vibelution\projects\<projectId>` |
| Instance data | `…\instances\<instanceId>\data` |
| Runtime / logs / cache | `…\instances\<instanceId>\{runtime,logs,cache}` |
| Project memory | `…\memory`（跨实例共享，不是运行时事实源） |

旧版 `%USERPROFILE%\Documents\Vibelution\data` 与项目根
`workspace/.runtime/logs/.docs/project-memory` 只在迁移完成前保持活跃。
迁移规则见 [ADR 0008](../../adr/0008-project-mutable-state-lives-outside-source-tree.md)。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `VIBELUTION_CONFIG_PATH` | 直接指定 `config.toml` 绝对路径 |
| `VIBELUTION_CONFIG_HOME` | 指定配置目录（其下读 `config.toml`） |
| `VIBELUTION_DATA_HOME` | 数据根 |
| `VIBELUTION_PROJECTS_HOME` | 覆盖项目状态总根（默认 `%LOCALAPPDATA%\Vibelution\projects`） |
| `VIBELUTION_ENABLE_USER_ENV_FALLBACK` | Windows 下允许回退读用户级环境变量中的 API Key |

实现：`config/paths.py`、`vibelution_storage.py`。
决策锁定：[ADR 0003](../../adr/0003-operator-config-lives-outside-repo.md)、[ADR 0008](../../adr/0008-project-mutable-state-lives-outside-source-tree.md)。

## 清点与迁移

先只读清点；确认当前 checkout 没有 Launcher、Runtime Manager、测试或 Agent
写入后再执行 apply：

```powershell
python scripts/migrate_project_storage.py inventory --project <project-root>
python scripts/migrate_project_storage.py apply --project <project-root>
```

`apply` 只复制并验证，不删除旧数据；冲突或源文件变化会阻止切换。需要回退时
执行 `rollback`，它只归档切换 marker，两边数据都保留。

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
