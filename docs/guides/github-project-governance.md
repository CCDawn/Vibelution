# 本地开源项目治理参考

项目内 Agent 和外部开发 Agent 使用同一个 GitHub 项目库，查询只读，不执行外部代码。

## 两类入口

- 项目内 Agent：通用基座 `core/core_prompt/COMMON.md` 在非平凡开发/治理任务开始时提示检索。只有本轮已提供 `github_project_library_search_tool` 时调用，不扩大工具授权。
- 开发 Agent：按 `AGENTS.md` 运行 `scripts/task_brief.py --task "前端治理" --files web/src/routes/chat`。简报自动检索本地项目卡片，最多返回 5 项；`--json` 可取得相同结构化结果。
- 显式阅读：用轻量 `agent_log_context.py` 解析 `activePaths.memory`，再读 `github-projects/INDEX.md`。不为定位此索引运行全量存储盘点。

可用查询包括“前端治理”“后端治理”“工具权限审批”“工作流检查点恢复”。查询和排序也使用已有项目元数据与有界 README token；它们只用于发现候选。

## 来源与边界

| 内容 | 唯一来源 |
| --- | --- |
| 项目身份、版本、许可、克隆状态 | 外置 `github-projects/registry.json` |
| 治理能力、借鉴切片、适用 owner、审查版本与证据位置 | `core/web/services/github_project_governance_catalog.py` |
| 人读索引 | 由上述来源生成的 `github-projects/INDEX.md`，不手改 |
| Agent 检索卡片与开发简报 | 由现有 `github_project_library_service.py` 只读生成 |

首批 10 个参考有固定版本的源码与测试配置定位；其他登记项目仍可检索，但不自动认定成熟。

- `ready`：克隆完成，不代表工程质量。
- `static_reviewed`：登记 HEAD 与已审查版本一致，证据文件存在；证据范围是静态源码和测试配置，未执行上游项目或验证 CI 结果。
- `review_required`：登记版本改变、克隆未就绪或证据文件缺失。旧审查版本保留，需重新核查后更新版本化 catalog。

卡片的 `governanceReview.evidenceRefs` 指向具体源码和测试配置，`reuseBoundary` 说明架构与许可限制。固定 HEAD 的代码才是实现证据；项目介绍、卡片和 README 不能成为新的项目规范或 transcript。

治理能力在读时合并，不能覆盖 registry 的 HEAD、许可与状态。常规检索不会改写 registry 或索引；克隆/更新时索引按现有生成路径更新。需要独立刷新已有索引时，只通过库服务的 `_write_index(root, registry)` 重建派生表，不重写 registry。

任务简报展示候选和公共基座提供检索指引，不保证模型每次调用或选对候选；这层行为需用真实 Agent 工具轨迹另验。
