# Vibelution Docs Index

`docs/` 是 Vibelution 跨会话详细文档的统一目录。根 `AGENTS.md` 是 Agent 入口；[standards/README.md](standards/README.md) 是现行规范权威地图。

## Current Entrypoints

| Area | Document | Authority |
| --- | --- | --- |
| Agent rules and routing | [../AGENTS.md](../AGENTS.md) | Root entry and global red lines |
| Detailed development standard | [standards/development-standard.md](standards/development-standard.md) | Canonical cross-project operating standard |
| Standards map | [standards/README.md](standards/README.md) | Canonical rule ownership and routing |
| Domain language | [agents/domain.md](agents/domain.md) | Canonical product and architecture vocabulary |
| Multi-Agent work | [agents/worktree-collaboration.md](agents/worktree-collaboration.md) | Worktree, claim, branch, and merge protocol |
| Tool authorization | [agents/tool-authorization-entrypoints.md](agents/tool-authorization-entrypoints.md) | Tool permission and routing entrypoints |
| Conversation flow | [agents/conversation-flow-map.md](agents/conversation-flow-map.md) | Chat turn data and projection map |
| Architecture decisions | [adr/](adr/) | Durable decisions and reasons |
| Tests | [../tests/README.md](../tests/README.md) | Test entrypoints and validation matrix |
| Runtime logging | [../core/logging/README.md](../core/logging/README.md) | Logging implementation map |
| Frontend product API | [../web/src/components/vui/README.md](../web/src/components/vui/README.md) | VUI local implementation map |
| Project memory | [../.docs/project-memory/INDEX.md](../.docs/project-memory/INDEX.md) | Current runtime/project state, not a normative source |

## Directory Classification

| Directory | Classification | Rule |
| --- | --- | --- |
| [standards/](standards/) | Current normative | Cross-module detailed rules live here |
| [agents/](agents/) | Current normative/reference | Collaboration, authorization, flow, and domain docs |
| [adr/](adr/) | Current decision record | Explains why stable architecture decisions exist |
| [ops/](ops/) | Current or historical operations | Each file must state status; historical snapshots are not authority |
| [testing/](testing/) | Evidence/reference | Test reports do not replace current test contracts |
| [plans/](plans/) | Planning | Plans are not active rules until promoted |
| [superpowers/](superpowers/) | Specs and plans | Status metadata controls lifecycle; not automatic authority |
| [prds/](prds/) | Product reference | Durable intent; verify against current implementation |
| [security/](security/) | Generated/reference | Verify source data and generation date |
| [archive/](archive/) | Historical | Never use as current rule source |

## Governance Rules

- 全局规范正文只写一次；`AGENTS.md`、本索引和模块 README 使用链接，不复制流程。
- 模块 README 可以保留局部 ownership、目录和实现地图，但不能声明竞争性的全局 canonical 规则。
- `core/core_prompt/COMMON.md` 与 `SOUL.md` 是运行时 Prompt 资产；它们和根 `AGENTS.md` 组成三核心基础。
- `.docs/project-memory/` 是可变状态和协作数据，不属于规范目录。
- 历史材料中的旧路径、旧技术栈和“当前”措辞仅代表当时快照。
- 现行前端栈是 Tailwind-first + VUI + shadcn/Radix；HeroUI 已移除。

## Spec And Plan Lifecycle

Spec/plan 状态使用 [development-standard.md §19.1](standards/development-standard.md#191-spec-and-plan-lifecycle) 定义的：

`draft`、`user-approved`、`active-plan`、`in-progress`、`implemented`、`superseded`、`blocked`、`historical`。

计划只有在 `AGENTS.md` 或 [standards/README.md](standards/README.md) 明确提升后，才能成为现行规范。
