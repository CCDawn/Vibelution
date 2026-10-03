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


REVIEWED_AT = "2026-10-03"
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
