"""Closed operator asset contracts over native Team, ToolPolicy and KB owners."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from core.web.services.agent_directory_service import TOOL_POLICY_WORKSPACE_SCOPES


Reference = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Fingerprint = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ToolName = Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z][a-z0-9_.:-]+$")]
Scope = Literal[tuple(TOOL_POLICY_WORKSPACE_SCOPES)]
Permission = Literal["read", "propose", "review"]
Approval = Literal["never", "on_request", "always"]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Patch(Closed):
    @model_validator(mode="after")
    def explicit_changes(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("At least one explicit, non-null change is required")
        return self


class ToolRule(Closed):
    # Native approvalGrants carry already-approved call credentials. They may
    # be retained by the owner, never manufactured through a policy patch.
    approval: Approval


class ToolPolicyPatch(Patch):
    allowedTools: list[ToolName] | None = Field(default=None, max_length=512)
    preferredTools: list[ToolName] | None = Field(default=None, max_length=512)
    blockedTools: list[ToolName] | None = Field(default=None, max_length=512)
    readScopes: list[Scope] | None = Field(default=None, max_length=256)
    writeScopes: list[Scope] | None = Field(default=None, max_length=256)
    allowedCommandKinds: list[Annotated[str, Field(min_length=1, max_length=80)]] | None = Field(default=None, max_length=128)
    blockedCommandPatterns: list[Annotated[str, Field(min_length=1, max_length=512)]] | None = Field(default=None, max_length=128)
    networkAccess: Literal["none", "restricted", "full", "inherit", "controlled"] | None = None
    mutationAccess: Literal["none", "workspace", "controlled", "inherit", "restricted"] | None = None
    delegationAccess: Literal["none", "assigned_only"] | None = None
    approvalOverrides: dict[ToolName, Approval] | None = None
    maxCallsPerTurn: int | None = Field(default=None, ge=0, le=10000)
    maxCallsPerTurnByModelFamily: dict[Annotated[str, Field(min_length=1, max_length=64)], Annotated[int, Field(ge=0, le=10000)]] | None = None
    perToolRules: dict[ToolName, ToolRule] | None = None


class TeamMember(Closed):
    memberId: str = Field(default="", max_length=96)
    agentId: Reference
    role: str = Field(default="", max_length=160)
    purpose: str = Field(default="", max_length=1000)
    responsibilities: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=8)


class TeamPatch(Patch):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    purpose: str | None = Field(default=None, max_length=1000)
    members: list[TeamMember] | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def unique_members(self):
        if self.members is not None:
            ids = [row.agentId for row in self.members]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate Team members are not allowed")
        return self


class TeamAssetQuery(Closed):
    team_id: Reference


class TeamUpdate(TeamAssetQuery):
    expected_team_fingerprint: Fingerprint
    updates: TeamPatch


class ToolPolicyQuery(Closed):
    agent_id: Reference


class ToolPolicyUpdate(ToolPolicyQuery):
    expected_config_revision: int = Field(ge=0)
    expected_agent_updated_at: str = Field(min_length=1, max_length=80)
    expected_policy_fingerprint: Fingerprint
    expected_registry_version: str = Field(min_length=1, max_length=160)
    expected_registry_fingerprint: str = Field(min_length=1, max_length=160)
    updates: ToolPolicyPatch


class KnowledgeACLQuery(Closed):
    knowledge_base_id: str = Field(min_length=1, max_length=390,
        pattern=r"^(?:(?:team|agent):[A-Za-z0-9][A-Za-z0-9_.-]{0,127}:)?[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class KnowledgeACLMutation(KnowledgeACLQuery):
    target_agent_id: Reference
    permissions: list[Permission] = Field(min_length=1, max_length=3)
    expected_acl_fingerprint: Fingerprint

    @model_validator(mode="after")
    def unique_permissions(self):
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("Duplicate permissions are not allowed")
        return self


class TeamAssetResponse(Closed):
    teamId: Reference
    name: str
    description: str
    purpose: str
    status: str
    members: list[TeamMember]
    updatedAt: str
    fingerprint: Fingerprint
    untrustedContent: Literal[True] = True


class ToolPolicyResponse(Closed):
    agentId: Reference
    configRevision: int
    agentUpdatedAt: str
    policyFingerprint: Fingerprint
    registryVersion: str
    registryFingerprint: str = Field(min_length=1, max_length=160)
    compiledMatches: bool
    policy: ToolPolicyPatch
    visibleTools: list[ToolName]
    executableTools: list[ToolName]
    untrustedContent: Literal[True] = True

    @field_serializer("policy")
    def serialize_policy(self, value):
        # Patch defaults are not explicit policy values. Keep them absent at
        # every nested wire/model boundary instead of turning them into nulls.
        return value.model_dump(exclude_none=True)


class KnowledgeACL(Closed):
    read: str
    propose: str
    review: str
    grants: dict[Literal["read", "propose", "review", "*"], list[Reference]]


class KnowledgeACLResponse(Closed):
    knowledgeBaseId: Reference
    scopedKnowledgeBaseId: str
    ownerType: Literal["team", "agent"]
    ownerId: Reference
    status: str
    updatedAt: str
    acl: KnowledgeACL
    fingerprint: Fingerprint
    untrustedContent: Literal[True] = True

    @model_validator(mode="after")
    def canonical_owner(self):
        if self.scopedKnowledgeBaseId != f"{self.ownerType}:{self.ownerId}:{self.knowledgeBaseId}":
            raise ValueError("Knowledge base scoped identity does not match its native owner")
        return self


class AssetMutationResponse(Closed):
    action: Literal["team_update", "agent_tool_policy_update", "knowledge_acl_grant", "knowledge_acl_revoke"]
    resourceId: str
    revision: int | None = None
    fingerprint: Fingerprint
    verified: bool
    untrustedContent: Literal[True] = True


ASSET_ACTION_MODELS = {"team_update": TeamUpdate, "agent_tool_policy_update": ToolPolicyUpdate,
                       "knowledge_acl_grant": KnowledgeACLMutation, "knowledge_acl_revoke": KnowledgeACLMutation}
ASSET_ACTION_SCOPES = {"team_update": "teams:write", "agent_tool_policy_update": "agents:tool-policy:write",
                       "knowledge_acl_grant": "knowledge:acl:write", "knowledge_acl_revoke": "knowledge:acl:write"}
ASSET_ACTION_HELP = {
    "team_update": "经原生管理审批维护已有团队名称、用途和成员；先读取原团队fingerprint，拒绝过期版本、系统团队和忙碌成员变更。原生成员身份与唯一归属规则继续生效。",
    "agent_tool_policy_update": "经原生管理审批修改目标Agent的声明式工具与范围策略；先读取配置版本、更新时间、policyFingerprint、registryVersion和registryFingerprint并原样传回，版本与内容指纹必须一致。声明中保留的工具仍受原生delegation门控制，不隐式授予全部工具、任意命令或审批凭据；更新不改变已接收Session的版本pin。",
    "knowledge_acl_grant": "经原生管理审批和独立知识ACL写授权，以真实操作者身份为active Agent增加显式read/propose/review；knowledge_base_id必须原样使用knowledge_acl_get返回的scopedKnowledgeBaseId，并携原ACL fingerprint，不冒充owner或reviewer。此授权不证明知识正文已读取。",
    "knowledge_acl_revoke": "经原生管理审批和独立知识ACL写授权，以真实操作者身份撤销指定Agent的显式read/propose/review；knowledge_base_id必须原样使用knowledge_acl_get返回的scopedKnowledgeBaseId，并携原ACL fingerprint。原生成员或owner固有权限不由此移除，当前权限须另行查询。",
}
