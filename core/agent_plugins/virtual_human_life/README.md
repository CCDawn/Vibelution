# `virtual_human_life` plugin pack

这是 Vibelution 第一方、按 `agentId` 显式绑定的虚拟人生活插件。未绑定或已禁用的 Agent 不创建生活数据，不注入 Prompt，不获得插件工具，也不会产生心跳或主动消息。

## 30 秒路由

| 需要修改 | 所有者 |
| --- | --- |
| manifest、能力、工具包和 Prompt Pack 元数据 | `manifest.py` |
| 绑定、生活状态、日程、心情、活动、日记、关系、主动消息账本和 Agent 生命周期 token | `service.py` |
| Agent 私有目录、原子 JSON/JSONL 读写和路径边界 | `storage.py` |
| 有界 Prompt Pack 文件列表和加载预算 | `prompt_pack.py` + `prompts/*.md` |
| Web/runtime facade、心跳 supervisor、receipt 恢复和 runtime-scene | `core/web/services/virtual_human_life_service.py` |
| 内部非用户 Session Turn | `core/web/services/session/proactive.py` |
| HTTP DTO 与薄路由 | `core/web/routes/agent_plugin*.py`、`core/web/routes/virtual_human_life*.py` |
| Agent 专用工具 | `tools/virtual_human_life_tools.py` |

## 不变量

- 计划不等于经历；只有带有效 outcome 的活动才能成为 Life Event、日记或长期记忆来源。
- 主动 Turn 不写 `user_message`；只有 assistant item 持久化并取得 receipt 后才计额度。
- `candidate/reserved/delivering` 使用稳定 token 和有效期；重启只按 receipt 对账或过期，不盲目重发。
- disable、archive、purge prepare 和 host stop 先使新工作失效，再取消插件拥有的主动 Turn。
- 工具可见性是 ToolPolicy 与 enabled binding 的交集；插件不能修改共享 ToolPolicy。
- 旧 `pet_info.json` 仅显式预览和导入，来源文件保留。

## 主测试

- `tests/test_virtual_human_life_plugin.py`
- `tests/test_virtual_human_session_proactive.py`
- `tests/test_virtual_human_life_api.py`
- `tests/test_virtual_human_life_tools.py`

产品契约见 [`docs/prds/2026-08-27-virtual-human-life-plugin.md`](../../../docs/prds/2026-08-27-virtual-human-life-plugin.md)。
