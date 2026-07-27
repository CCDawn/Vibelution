# Vibelution Standards

本目录是 Vibelution 跨模块详细规范的唯一权威目录。根目录 `AGENTS.md` 只保留全局红线和路由，不复制这里的流程正文。

## 权威顺序

1. 用户当前明确要求与授权边界；
2. 根目录 `AGENTS.md`；
3. 本目录中对应专项规范；
4. ADR 与模块 README；
5. 历史计划、报告和归档材料。

`core/core_prompt/COMMON.md` 与 `core/core_prompt/SOUL.md` 是运行时 Prompt 资产，不属于详细开发规范，也不扩大权限。

## 当前规范入口

| 任务或问题 | 权威文档 |
| --- | --- |
| 开发分级、BRT、来源权威、结构边界、验证、Git、Launcher、发布、完成条件 | [development-standard.md](development-standard.md) |
| 多 Agent、worktree、claim、merge 协作 | [../agents/worktree-collaboration.md](../agents/worktree-collaboration.md) |
| 领域词汇 | [../agents/domain.md](../agents/domain.md) |
| 工具授权入口 | [../agents/tool-authorization-entrypoints.md](../agents/tool-authorization-entrypoints.md) |
| 前端 VUI 实现地图 | [../../web/src/components/vui/README.md](../../web/src/components/vui/README.md) |
| 测试入口 | [../../tests/README.md](../../tests/README.md) |
| 运行日志实现地图 | [../../core/logging/README.md](../../core/logging/README.md) |
| 架构决策 | [../adr/](../adr/) |

## 边界

- 全局规则正文只写一次；其他文档使用链接。
- 模块 README 只负责局部 ownership、目录和实现地图，不声明竞争性的全局规则。
- `.docs/project-memory/` 是运行状态与协作数据，不是规范目录。
- `docs/plans/`、`docs/superpowers/` 和 `docs/archive/` 不是现行规则来源，除非本索引或 `AGENTS.md` 明确提升。
- 新增或修改全局规则时，必须同步检查 `AGENTS.md` 路由、相关守卫测试和项目记忆决策。

当前 `development-standard.md` 保留完整章节编号以降低迁移风险；后续只有在不复制规则正文且链接守卫可验证时，才按专题继续拆分。
