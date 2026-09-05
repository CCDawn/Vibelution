# 知识库管理 Agent 工作流程接入说明

状态：固定流程已接入知识库管理员的内置角色模板；生产运行验收单独记录，不等于已执行知识治理。核对日期：2026-09-05。

## 唯一流程正文与加载入口

管理流程正文在 [knowledge_steward.md](../../core/core_prompt/roles/knowledge_steward.md)。修改判断步骤、摄取路径、回读证据或阶段协议时只维护该文件；本文保留接入说明和场景走查，不再复制流程。

加载路径：角色 MD → [prompt_template_service](../../core/web/services/prompt_template_service.py) 的 `prompt-knowledge-steward` → Agent Prompt snapshot → 原有会话装配。
MD 从安装代码的项目根定位，在模板模块加载时读取；不依赖进程 cwd、用户目录或工作台内手工打开文件。
它是知识库管理员专用角色内容，不加入所有 Agent 共享的 COMMON / SOUL / AGENTS，不修改普通 Session 的接收、Journal、worker 或 SSE。

本次 `KNOWLEDGE_STEWARD_PROMPT_VERSION` 从原共享版本 16 独立为 17；旧内置记录沿既有 `repair_prompt_templates` 机制更新，旧 Prompt snapshot 由现有版本校验失效并重建。保留原来只处理已复核本轮候选的阶段协议。
后续修改角色 MD 时须同步提升该独立版本；运行中的服务需重新加载代码，既有轮次不会因磁盘 MD 修改而中途热替换。
原 Python 内联正文已移除；仓库 MD 是内置默认正文的维护来源，运行时索引仍沿用现有模板存储和编辑语义。

## 权限与写入职责

- 权限以运行时身份和服务校验为准，遵循[项目操作目录](project-operation-catalog.md)；本次不修改工具策略、知识库 ACL 或用户授权。
- 已核对运行配置中 `agent-knowledge-steward` 绑定该角色模板并配置管理工具。其 read / propose / review / rate 范围列表为空；[工具实现](../../tools/team_knowledge_tools.py)将空列表解释为不额外收窄，不能单凭列表推导最终访问权。
- [权限实现](../../core/web/services/team_knowledge/permissions.py)允许系统知识库管理员 read / propose 和来源收件箱审核；普通提案 review / 正式评级应用仍按 owner、成员角色或显式 ACL 判断。评级建议有自己的受控入口。
- 知识内容与审核继续由 [Team Knowledge](../../core/web/services/team_knowledge/README.md)负责；统一检索与图谱遵守[只读边界](../../core/web/services/memory_rag_services.md)。
- 单库领域范围、来源标准、时效要求和审核责任人继续使用既有策略；不复制一份与运行时竞争的权限表。

## 三个场景走查

以下为基于代码和测试的设计走查，使用示意对象，不是对生产知识库的实跑记录。

| 场景 | 推演与应有结果 | 当前能力边界 |
| --- | --- | --- |
| 新增：已进入团队 inbox 的实验记录 | 确认目标与身份 → 查重 → 核验结论与来源 → 受控 inbox 摄取 → 检查实际 item → 检索回读 | [摄取测试](../../tests/test_team_knowledge_tools.py)覆盖普通来源仅生成 pending、已审核 inbox 可入库、入库成功但实验衔接失败；不增加固定人工二审 |
| 纠错：同一实验条件下，复核记录推翻原测量值 | 查回旧条目 → 比较原始结果与条件 → 提出更正及引用影响 → 有权入口处理旧条目 → 回读 | 现有管理员工具没有正式条目正文替换能力；可提交更正材料或建议，不能声称旧结论已修复 |
| 冲突：两份报告给出相反结论 | 比较版本、时间和条件 → 区分适用范围或保留双方 → 形成冲突说明及必要复审建议 | 公共目录支持显式冲突字段，但当前管理员工具未提供该关系写入入口；评级建议不代表关系已落盘 |

## 验证与真实限制

- [Prompt 测试](../../tests/test_prompt_template_service.py)覆盖最终 snapshot 包含且只包含一次固定流程、旧版管理员模板修复、旧 snapshot 失效，以及其他角色记录不变且不注入管理流程。
- [阶段工具](../../tools/source_collection_stage_tools.py)仍以真实任务和 `result_json` 回写；独立 inbox 摄取与阶段摄取使用各自回执，不混淆任务 completed、提案 submitted 和正式入库。
- 全文回读、正式提案审核应用、正式评级应用、旧知识替换、冲突关系写入及来源失效处理，需分别确认实际可调用入口；服务函数存在不等于 Agent 获得工具。
- 工作台 `canDirectlyApplyKnowledge: false` 描述建议面；inbox 摄取另有受控直接入库路径。角色流程区分两者；本次没有修改工作台 DTO。
- 本次运行配置核对来自已解析的运行目录；工作台 API 返回 403，未绕过鉴权，未通过该 API 执行管理任务。
- 未新增事件监听、定时任务或后台模型调用，未修改真实知识条目。固定流程接入的代码验证不能替代实际 Agent 管理效果验收。

## 复用依据

- 本地复用：现有角色模板、`builtinContentVersion` 修复、Prompt snapshot 版本校验，以及现有摄取／检索工具。没有新依赖或第二套 Prompt 注入机制。
- [LLM Wiki Agent](https://github.com/SamurAIGPT/llm-wiki-agent/tree/4ea2c7f916a8f7de6c787d1be014cd392250c161)：参考来源、概念、综合页组织思路；不采用完整文件覆盖与有限历史上下文的导入方式。
- [Onyx Agent Wiki](https://github.com/onyx-dot-app/agent-wiki/tree/117b5872de55539bceb39388ef24381b7da1e7a9)：参考检测与提案分离、文字来源归属；不引入其代码、依赖或存储，Elastic License 2.0 不按 MIT 对待。
