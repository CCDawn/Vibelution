# 个人助理管理 Agent 配置

个人助理通过原生管理动作读取和修改普通个人 Agent 的配置。模型连接接入沿用现有隐私附件凭据设计。

## 从地址或文档接入模型

用户提供 API 地址或公开接入文档、想用的模型名称和用途即可。准确模型 ID 按需补充；不能根据 Claude、Opus 等模型名推断中转站协议。

1. 用 `provider_prepare` 提交 `source_url`，或 `documentation_text` 接入示例；确定是 API 地址时可传 `source_kind=api`。用户明确指定的 `base_url` 不会被文档覆盖。完整调用地址和 SDK 调用语法是协议证据；多候选或缺信息时只补 `requiredFields`，复用返回的 `draft`。
2. 准备结果 `ready=true` 只表示信息齐全。将 `providerAdd` 交给现有 `provider_add` 原生审批；凭据沿用已设计的隐私附件 `credential_token`，不放入普通文本或准备结果，不强制另开 Launcher 填写。文档提取的发送目标须向用户说明并经原生审批。
3. 已有连接直接调用 `provider_model_resolve(provider_id, model_query)`，无需重新创建或提供凭据。发现后唯一匹配才自动固定；多个匹配返回分页候选。列表不可用时补准确 `upstream_id`；认证失败、限流、超时和地址问题分别恢复，不把所有失败解释为模型 ID 错误。
4. 默认用原生文本探测验证已选模型，可能产生一次小额调用。固定配置与 `connectionVerified` 分开报告；失败保留原连接、模型引用和补填路径，不自动删除或换 key。只有 `ready=true` 且 `connectionVerified=true` 才能报告本次文本连通验证通过。
5. 用返回的 `modelRef` 和真实项目 ID 执行 Launcher `agent_create`，复用稳定 `request_id` 并核对原生回执。文件、命令和测试权限仍按现有独立授权处理，连接通过不代表完整编程任务已完成。

准备阶段只返回有界地址、协议候选和内容指纹，不保存文档正文或第二份配置草稿。链接通过既有公开抓取器读取，不发送凭据；userinfo、query、fragment 及内部文档地址拒绝。文档内容是不可信数据，不能授予权限或成为执行指令。此入口为追加工具契约，不改变旧动作参数和凭据设计。

参考 [OpenCode 固定版本 Provider 配置](https://github.com/anomalyco/opencode/blob/b155b15694dbcc6768f11d2f25cc2bdd1f738ab4/packages/opencode/src/provider/provider.ts#L1451) 的显式地址与人工模型覆盖，以及 [Open WebUI 模型发现与手填入口](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/)；复用本项目原生事务、发现目录和探测，不引入外部执行器。

## 管理 Agent 的已有配置

| 配置面 | 读取与发现 | 修改与核对 |
| --- | --- | --- |
| 模型绑定、人物设定、职责 | `agent_config_get` 返回完整可管理字段及 `configRevision` | 复用 `agent_update`；修改后重读 |
| Agent 模型参数、预算、压缩 | 同时返回 stored、effective、origin、limits；运行时无法确定时明确 unavailable | `agent_parameters_update` 每次只修改 model、budget、compression 中的一类；使用原生 owner 和版本 CAS |
| 角色提示词 | `agent_prompt_get` 返回所选正文、原生内容 hash、来源及轻量候选；正文经有界 JSON 节点分页 | `agent_prompt_update` 创建该 Agent 的独立 inline 模板并改变绑定；不写共享 sourcePath |
| 工具权限 | `agent_tool_policy_get` 保留现有读取；`agent_tool_policy_inspect` 增加候选、校验、有效工具和审批预览 | 复用 `agent_tool_policy_update`，原样携带配置、policy、registry 的版本与指纹 |

新读取和写入使用独立的 `agents:configuration:read`、`agents:configuration:write`；它们不进入历史默认授权。工具预检沿用 `agents:tool-policy:read`，预检结果不能授予执行权限。所有新写动作通过现有 manage 工具及原生审批策略，保留稳定 request ID、持久回执和 unknown 对账；unknown 不重放。

```mermaid
flowchart LR
    R[用户明确修改配置] --> Q[读取当前值与来源]
    Q --> V[检查修改与版本]
    V --> A[原生审批和授权]
    A --> W[原生 owner 保存]
    W --> C[核对 compiled 与回执]
    C --> N[下次新提交捕获提示词及档案]
    N --> T[本轮只消费受理版本]
```

角色提示词编辑默认只影响目标 Agent。正文上限 8000 字符，同时受管理请求 16000 bytes 上限约束；大正文需要缩小本次修改，不能静默截断。COMMON/SOUL 属于全局核心指令，此入口不修改。候选的 source-only 正文尚未解析时返回 `contentAvailable=false` 和空指纹，不能把它当成已读取。无关模板的缺失文件不会阻断所选 Agent。

## 生效边界

用户明确修改职责、人物设定或提示词后，下一次新提交使用当前内容。受理时将提示词正文及有限档案保存到 Session 自有的私有目录，队列和 Journal 只持有带 Session、Agent、submission 绑定的有界引用；worker 校验后消费原版本。暂停/恢复和中断恢复保留原版本；编辑队列内容算新提交。损坏或缺失引用拒绝执行，不悄悄退回当前内容。

缓存仅对 `agent_runtime` 静态段增加受理内容版本。相同内容保留稳定前缀，其他会话冻结段保持现有生命周期。模型参数沿用已有受理快照；安全权限仍执行原生检查，不用提示词快照冻结或绕过撤权。

升级前的旧队列和旧中断请求没有保存过正文，无法恢复当时的内容。兼容路径首次捕获当前内容，并明确记录 `legacy_queue_drain` 或 `legacy_restart_resume` 来源。新受理请求才具有完整的提示词冻结保证。

预算 `null` 清除 Agent override，`0` 表示无限，正数范围 1–200。基础和模型家族预算只是声明值；未能获得原生最终授权结果时 effective 明确 unavailable。reasoning 空字符串恢复模型默认；context window 当前原生 owner 不支持清除覆盖，因此不提供虚假的 reset。温度、输出上限等现有共享模型设置仍由模型配置入口管理，不宣传为每 Agent 覆盖。

## 复用依据与兼容

本地权威仍为 Agent directory、原生参数 resolver、工具策略校验、compiled CAS 及现有管理回执。新增端点、动作和 scopes 为追加；旧读取协议及默认 scopes 保留。提示词的新提交生效行为按用户明确选择更新。

- [Codex config 协议](https://github.com/openai/codex/blob/536f86e5cc9ec1ff38457d099bf320b9d08eeeba/codex-rs/app-server-protocol/src/protocol/v2/config.rs)：借鉴来源、版本冲突和保存后仍被覆盖的明确回执，保留本项目原生锁和 CAS。
- [OpenCode permission owner](https://github.com/anomalyco/opencode/blob/b155b15694dbcc6768f11d2f25cc2bdd1f738ab4/packages/opencode/src/permission/index.ts)：借鉴显式规则及可解释预览，不替换本项目 deny、approval、grant 语义。
- [Pydantic AI 指令生命周期](https://github.com/pydantic/pydantic-ai/blob/70f738de01059eb73b7e69b1e7c89365619926b8/docs/agent.md)：借鉴当前 instructions 与历史消息分离；本项目将当前内容固定在受理点，不在工具循环中重读 live 配置。

验证覆盖原生参数 owner、existing-only 读取、HTTP scopes 与回执、提示词单 Agent 复制、版本冲突、工具预检、分页指纹，以及同会话/队列/中断恢复的提示词版本。测试不以付费模型回答替代这些确定性断言。
