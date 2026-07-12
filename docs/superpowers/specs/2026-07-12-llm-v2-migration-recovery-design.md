# Schema v2 迁移恢复与设置对齐设计

## 目标

让旧 Schema v1 中被标记为 `relay`、但实际指向 loopback 地址的模型服务，能够安全迁移为 Schema v2 的 `local_runtime` Provider；同时让设置页在迁移预览失效或 Apply 状态冲突后清除陈旧的 `READY` 预览，并提示重新生成。

## 已确认问题

- 当前 operator config 中 `provider_127` 的旧 `kind` 为 `relay`，但 `base_url` 指向 localhost。
- 迁移按旧 `kind` 生成非本地 Provider，随后在 `validate_config` 阶段被安全校验拒绝。
- Launcher 后端重启会清空进程内迁移预览，但设置页仍可能保留旧的 `READY` 状态；Apply 只显示原始 JSON 错误。
- 所有失败路径均在写入前终止或由迁移器自动回滚，当前 operator config 仍为 Schema v1。

## 方案

### 后端迁移分类

迁移器以显式本地 `kind` 或 loopback endpoint 作为 `local_runtime` 的判据。loopback 包括 `localhost`、IPv4 loopback 网段和 IPv6 loopback；不把普通局域网地址自动视为本地，以免误分类内网中转站。

Provider ID、模型 upstream ID、base URL、credential ref 和 model alias 映射保持不变。Schema v2 校验规则不放宽。

### 设置页恢复

把迁移 Apply 错误的恢复判断放入 `configRouteLogic.ts` 的纯函数。遇到 `migration_request_rejected` 或 `migration_state_conflict` 时：

- 清除当前 `migrationPreview`；
- 显示“预览已失效，请重新生成”的可操作提示；
- 不自动重试 Apply，不绕过最终确认。

其他错误继续显示原始可读消息，不改变既有处理。

## 数据流

1. 用户生成迁移预览并显式裁决 artifact 冲突。
2. 迁移器规范化 endpoint，并把 loopback 服务分类为 `local_runtime`。
3. Apply 创建备份与 manifest，写入 Schema v2，重写 live references，校验并重载。
4. 若 Apply 请求因预览/状态失效而失败，前端清除旧预览，要求重新生成。
5. Launcher 刷新后，设置页展示 Provider-first 模型中心、模型编辑和 API Key 环境变量入口。

## 验证

- Python RED/GREEN：旧 `relay` + loopback endpoint 迁移后是 `local_runtime`，完整 Apply 不再触发 localhost 校验错误。
- TypeScript RED/GREEN：迁移失效错误返回恢复提示，非迁移错误不被误判。
- 聚焦回归：`tests/test_model_config_migration.py`、`configRouteLogic.test.ts`、`ConfigRoute.layout.test.ts`。
- 前端构建：`npm run build`。
- 真实闭环：READY 预览、备份 manifest、Schema v2 落盘、引用扫描、Launcher 刷新、桌面与窄屏设置页验收。

## 非目标

- 不修改 API Key 值，不把密钥写进 `config.toml`。
- 不放宽 localhost Provider 的安全校验。
- 不重命名现有模型或 Provider，不移除兼容 alias。
- 不推送远端、不创建 PR、不调整版本号。
