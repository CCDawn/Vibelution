"""Reviewed governance slices; clone identity and availability stay in the registry.

These are discovery assessments of pinned local snapshots, not runtime acceptance
or permission to copy upstream code. Unknown projects remain unreviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GovernanceProfile:
    project_id: str
    head_sha: str
    areas: tuple[str, ...]
    capabilities: tuple[str, ...]
    borrowed_slice: str
    local_owners: tuple[str, ...]
    boundary: str
    source_path: str
    source_line: int
    test_configuration: str


REVIEWED_AT = "2026-10-07"
PROFILES = (
    GovernanceProfile(
        "anomalyco__opencode", "b155b15694dbcc6768f11d2f25cc2bdd1f738ab4",
        ("frontend",), ("前端治理", "实时状态", "会话事件", "事件归约", "frontend governance"),
        "集中归约实时事件，清理被裁剪会话的缓存。",
        ("web/src/routes/chat",),
        "参考事件和缓存边界；保留原生 Session/SSE 权威，不另建 transcript。",
        "packages/app/src/context/global-sync/event-reducer.ts", 109, ".github/workflows/test.yml",
    ),
    GovernanceProfile(
        "shadcn-ui__ui", "25be24cca34d06eed29a4779c3f48c4816aa812c",
        ("frontend",), ("前端治理", "组件登记", "设计系统", "组件契约", "frontend governance"),
        "用结构化 schema 描述组件依赖、文件与设计变量，并做机器校验。",
        ("web/src/components/vui",),
        "经 VUI 产品 API 与 shadcn renderer 适配；不在业务路由引入第二套组件系统。",
        "packages/shadcn/src/registry/schema.ts", 158, ".github/workflows/test.yml",
    ),
    GovernanceProfile(
        "TanStack__query", "ac2b61230ea35b90b177ba35dc030598bac9c9a6",
        ("frontend",), ("前端治理", "缓存状态", "请求状态", "查询失效", "frontend governance"),
        "分离资源数据、错误、失效和抓取状态。",
        ("web/src/api",),
        "用于服务端资源缓存；不替代原生会话、持久化或 transcript 权威。",
        "packages/query-core/src/query.ts", 48, ".github/workflows/pr.yml",
    ),
    GovernanceProfile(
        "langgenius__dify", "fcb380044cd820c501aad70f157460d257e34dfd",
        ("frontend",), ("前端治理", "类型化接口", "API 分层", "查询层", "frontend governance"),
        "以类型化 API 合约和 query 工具划分前端服务边界。",
        ("web/src/api",),
        "设计参考；修改版 Apache 有多租户与前端标识限制，复制代码前另核许可。",
        "web/service/client.ts", 18, ".github/workflows/main-ci.yml",
    ),
    GovernanceProfile(
        "FlowiseAI__Flowise", "9291856d1ea4a4ceea9f8fef8ce14f4f6c81e8eb",
        ("frontend",), ("前端治理", "网络层", "认证刷新", "frontend governance"),
        "集中 HTTP 客户端和认证刷新处理。",
        ("web/src/api",),
        "参考网络边界；不照搬全局 store，enterprise 与部分文件使用商业许可。",
        "packages/ui/src/api/client.js", 5, ".github/workflows/main.yml",
    ),
    GovernanceProfile(
        "openai__codex", "536f86e5cc9ec1ff38457d099bf320b9d08eeeba",
        ("backend",), ("后端治理", "工具权限审批", "策略判决", "沙箱执行", "backend governance"),
        "分离命令策略判决、审批和工具执行。",
        ("core/orchestration", "tools"),
        "参考策略与执行契约；Rust 命令沙箱需要适配，不替换现有 ToolPolicy。",
        "codex-rs/core/src/exec_policy.rs", 208, ".github/workflows/rust-ci.yml",
    ),
    GovernanceProfile(
        "openai__openai-agents-python", "eb3a5d5b5d1539e304c452b207639a320d89ac6e",
        ("backend",), ("后端治理", "工具权限审批", "中断恢复", "类型约束", "backend governance"),
        "按调用上下文决定工具批准，并在运行中断后批准或拒绝再恢复。",
        ("core/orchestration", "tools"),
        "SDK 机制参考；身份、ACL 与生产存储仍由 Vibelution 持有。",
        "src/agents/tool.py", 486, ".github/workflows/tests.yml",
    ),
    GovernanceProfile(
        "langchain-ai__langgraph", "38031739e551638e373fb553453256c23feeb41f",
        ("backend",), ("后端治理", "工作流检查点恢复", "失败恢复", "checkpoint recovery", "backend governance"),
        "检查点版本契约与节点失败后 pending-write 的局部恢复测试。",
        ("core/research/workflow",),
        "编排机制参考；图状态不提供产品身份授权，不另建会话 transcript。",
        "libs/langgraph/tests/test_pregel.py", 891, ".github/workflows/ci.yml",
    ),
    GovernanceProfile(
        "OpenHands__software-agent-sdk", "22c85eb0e0db8f4386380d095e9fe6933af2e65f",
        ("backend",), ("后端治理", "会话占用", "租约", "并发互斥", "backend governance"),
        "用 owner、generation 和 TTL 管理会话占用。",
        ("core/orchestration",),
        "SDK/Agent Server 参考，不等同完整 workbench；保留原生会话 authority。",
        "openhands-agent-server/openhands/agent_server/conversation_lease.py", 101, ".github/workflows/tests.yml",
    ),
    GovernanceProfile(
        "pydantic__pydantic-ai", "70f738de01059eb73b7e69b1e7c89365619926b8",
        ("backend",), ("后端治理", "工具权限审批", "类型约束", "backend governance"),
        "在工具集边界组合批准门控与类型约束。",
        ("tools", "core/orchestration"),
        "框架 SDK 参考；不默认新增依赖或替代现有工具授权链。",
        "pydantic_ai_slim/pydantic_ai/toolsets/approval_required.py", 15, ".github/workflows/ci.yml",
    ),
    GovernanceProfile(
        "zai-org__ZCode", "872ad960de7ec172591f7e1952f7849229f94521",
        ("backend",), ("后端治理", "多agent编排", "子agent派发", "会话邮箱", "backend governance"),
        "子 agent 派发返回 agentId 并可 SendMessage 续聊，跨 agent 消息经 unread/read 目录邮箱 drain。",
        ("core/orchestration", "core/chatroom"),
        "参考派发-续聊契约与邮箱到达顺序；保留原生 Session/SSE 权威，mailbox 只做到达不建第二 transcript。",
        "apps/zcode-cli/packages/adapters/src/mailbox/index.ts", 18, "architecture-policy.yaml",
    ),
    GovernanceProfile(
        "microsoft__autogen", "027ecf0a379bcc1d09956d46d12d44a3ad9cee14",
        ("backend",), ("后端治理", "点对点路由", "编排显式化", "多agent编排", "backend governance"),
        "共享广播房式 GroupChat 迁移到显式 teams 编排，core 层用 recipient 定向 envelope 做点对点路由。",
        ("core/orchestration",),
        "架构演进参考；不引入 actor 运行时，登记许可 CC-BY-4.0，复制代码前另核包内 LICENSE。",
        "python/packages/autogen-core/src/autogen_core/_single_threaded_agent_runtime.py", 71, ".github/workflows/checks.yml",
    ),
    GovernanceProfile(
        "crewAIInc__crewAI", "19d4154b0b96a290e7eb17bbc28b1b2e9c5e8156",
        ("backend",), ("后端治理", "事件驱动编排", "层级编排", "事件时间线", "backend governance"),
        "以 @listen/@router 事件触发组装层级编排，Crew 降级为 Flow 内可组合步骤。",
        ("core/orchestration", "core/chatroom"),
        "DSL 形态参考；事件时间线权威仍在 chatroom，不引入框架运行时。",
        "lib/crewai/src/crewai/flow/dsl/_listen.py", 18, ".github/workflows/tests.yml",
    ),
    GovernanceProfile(
        "a2aproject__A2A", "7295b180ee91ee3a18fd1f1ee2c3e6ad8a441305",
        ("backend",), ("后端治理", "任务生命周期", "交付产物", "agent-as-server", "backend governance"),
        "Task 携唯一 ID 走定义生命周期，Artifact 是交付权威，生命周期流到终态必须闭合。",
        ("core/orchestration", "core/chatroom"),
        "协议契约参考；跨 agent 不共享内部上下文，身份、ACL 与存储仍由 Vibelution 持有。",
        "docs/specification.md", 210, "specification/buf.yaml",
    ),
    GovernanceProfile(
        "google-gemini__gemini-cli", "ef59c532f07fbb3a58dd68bac024ae217e9c73ce",
        ("backend",), ("后端治理", "计划模式", "任务分解", "编排反面对照", "backend governance"),
        "规划收敛为主 agent 的只读计划模式加计划到任务图的强制分解，不递归派生规划者 agent。",
        ("core/orchestration",),
        "反面对照参考；借鉴模式门控与任务拓扑约束，不据此否定或复制其子 agent 实现。",
        "packages/core/src/prompts/snippets.ts", 590, ".github/workflows/ci.yml",
    ),
    GovernanceProfile(
        "RooCodeInc__Roo-Code", "b867ec9145750d0ae1ff7f02d35406e9bf2a0b16",
        ("backend",), ("后端治理", "子任务委派", "结果回传", "多agent编排", "backend governance"),
        "new_task 以 parentTaskId 委派子任务，tool_result 携子任务回执，父任务免交互续跑。",
        ("core/orchestration", "core/chatroom"),
        "委派-回传契约参考；子任务证据写入事件时间线，不复制 VSCode 侧任务栈。",
        "src/core/tools/NewTaskTool.ts", 113, ".github/workflows/code-qa.yml",
    ),
)
_BY_ID = {profile.project_id: profile for profile in PROFILES}


def governance_metadata(library_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    """Return bounded assessment pointers without changing clone metadata."""
    profile = _BY_ID.get(str(project.get("projectId") or ""))
    if profile is None:
        return {}
    repo = library_root / "repos" / profile.project_id
    references = (
        (profile.source_path, profile.source_line, "source"),
        (profile.test_configuration, 1, "test_configuration"),
    )
    reason = ""
    if project.get("headSha") != profile.head_sha:
        reason = "snapshot_changed"
    elif project.get("status") != "ready":
        reason = "clone_not_ready"
    elif any(not (repo / path).is_file() for path, _, _ in references):
        reason = "evidence_missing"
    return {
        "capabilities": list(profile.capabilities),
        "useCases": [profile.borrowed_slice],
        "governanceReview": {
            "status": "review_required" if reason else "static_reviewed",
            "reason": reason,
            "reviewedAt": REVIEWED_AT,
            "reviewedHeadSha": profile.head_sha,
            "assessmentScope": "local_source_and_test_configuration",
            "areas": list(profile.areas),
            "borrowedSlice": profile.borrowed_slice,
            "localOwners": list(profile.local_owners),
            "reuseBoundary": profile.boundary,
            "evidenceRefs": [
                {"path": path, "line": line, "kind": kind, "absolutePath": str(repo / path)}
                for path, line, kind in references
            ],
        },
    }
