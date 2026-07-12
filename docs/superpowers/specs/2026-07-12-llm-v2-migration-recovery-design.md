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

### 现有 Provider 的 API Key 编辑

Schema v2 Provider 工作台在“连接”页为需要凭据的现有 Provider 提供“设置 API Key”入口。入口打开独立的密码输入区，只接收本次新值，不展示当前 secret，也不展示内部 `credential_ref`。

提交时复用现有 `PUT /api/config/draft/providers/{provider_id}` 契约，保持 Provider 路由和模型不变，仅通过 `credentialValue` 把 secret 注册为服务端 pending token。响应同步回 Config 草稿后，用户仍需点击全局“保存到外部配置”；保存阶段把 secret 写入既有凭据引用对应的用户级环境变量，公开 `config.toml` 只保留引用。

`credentialState == "not_required"` 的 Provider 不开放入口。空值不能提交；取消、Provider 切换和成功提交都会清空本地输入。错误信息不得包含输入值。

## 数据流

1. 用户生成迁移预览并显式裁决 artifact 冲突。
2. 迁移器规范化 endpoint，并把 loopback 服务分类为 `local_runtime`。
3. Apply 创建备份与 manifest，写入 Schema v2，重写 live references，校验并重载。
4. 若 Apply 请求因预览/状态失效而失败，前端清除旧预览，要求重新生成。
5. Launcher 刷新后，设置页展示 Provider-first 模型中心；现有 Provider 可通过密码输入把 API Key 加入服务端草稿，再由全局保存写入用户环境变量。

## 验证

- Python RED/GREEN：旧 `relay` + loopback endpoint 迁移后是 `local_runtime`，完整 Apply 不再触发 localhost 校验错误。
- TypeScript RED/GREEN：迁移失效错误返回恢复提示，非迁移错误不被误判。
- TypeScript RED/GREEN：Provider 面板暴露受控的 API Key 入口；ConfigRoute 使用现有 update-provider 契约提交 `credentialValue`，成功后清空输入并保留全局保存门禁。
- 聚焦回归：`tests/test_model_config_migration.py`、`configRouteLogic.test.ts`、`ConfigRoute.layout.test.ts`。
- 前端构建：`npm run build`。
- 真实闭环：READY 预览、备份 manifest、Schema v2 落盘、引用扫描、Launcher 刷新、桌面与窄屏设置页验收。

## 非目标

- 不修改 API Key 值，不把密钥写进 `config.toml`。
- 不放宽 localhost Provider 的安全校验。
- 不重命名现有模型或 Provider，不移除兼容 alias。
- 不推送远端、不创建 PR、不调整版本号。
