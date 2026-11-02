"""Closed Team lifecycle commands over the existing native Team authority."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .asset_contracts import Closed, Fingerprint, Reference, TeamMember


class TeamCreate(Closed):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    purpose: str = Field(default="", max_length=1000)
    members: list[TeamMember] = Field(default_factory=list, max_length=120)

    @model_validator(mode="after")
    def unique_members(self):
        ids = [member.agentId for member in self.members]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate Team members are not allowed")
        return self


class TeamMemberAdd(Closed):
    team_id: Reference
    expected_team_fingerprint: Fingerprint
    member: TeamMember


class TeamMemberRemove(Closed):
    team_id: Reference
    expected_team_fingerprint: Fingerprint
    agent_id: Reference


class TeamArchive(Closed):
    team_id: Reference
    expected_team_fingerprint: Fingerprint
    expected_member_agent_ids: list[Reference] = Field(max_length=120)
    expected_linked_chat_room_id: Reference | Literal[""]

    @model_validator(mode="after")
    def unique_members(self):
        if len(self.expected_member_agent_ids) != len(set(self.expected_member_agent_ids)):
            raise ValueError("Duplicate Team members are not allowed")
        return self


TEAM_ARCHIVE_EFFECTS = (
    "归档团队",
    "归档团队成员 Agent 并封存其会话",
    "删除团队全部归属群聊，清理成员在其他群聊的关联，并按原生规则解散因此变空的群聊；主关联群聊 ID 不是全部影响范围",
)


class TeamArchivePreviewResponse(Closed):
    teamId: Reference
    fingerprint: Fingerprint
    memberAgentIds: list[Reference] = Field(max_length=120)
    linkedChatRoomId: Reference | Literal[""]
    effects: list[str]
    untrustedContent: Literal[True] = True

    @model_validator(mode="after")
    def native_effects(self):
        if self.effects != list(TEAM_ARCHIVE_EFFECTS):
            raise ValueError("Team archive effects must describe the native cascade")
        if len(self.memberAgentIds) != len(set(self.memberAgentIds)):
            raise ValueError("Duplicate Team members are not allowed")
        return self


TEAM_LIFECYCLE_ACTION_MODELS = {
    "team_create": TeamCreate, "team_member_add": TeamMemberAdd,
    "team_member_remove": TeamMemberRemove, "team_archive": TeamArchive,
}
TEAM_LIFECYCLE_ACTION_SCOPES = {
    "team_create": "teams:create", "team_member_add": "teams:write",
    "team_member_remove": "teams:write", "team_archive": "teams:archive",
}
TEAM_LIFECYCLE_ACTION_HELP = {
    "team_create": "经原生管理审批创建普通自定义团队，成员须为 active Agent 且只能属于一个 active 团队；原生流程会建立成员会话、关联群聊和画布。OPERATION_UNCONFIRMED 表示可能已有副作用，须核查，禁止重放。",
    "team_member_add": "经原生管理审批为团队增加一个成员；先读取团队 fingerprint 并原样传回，拒绝重复成员、过期版本、系统/归档团队和归档入场占用。沿用原生成员唯一归属、会话及群聊同步规则。OPERATION_UNCONFIRMED 须核查，禁止重放。",
    "team_member_remove": "经原生管理审批从团队移除一个成员，保留该 Agent 和会话历史；先读取团队 fingerprint 并原样传回，拒绝不存在的成员、过期版本、系统/归档团队和归档入场占用。OPERATION_UNCONFIRMED 须核查，禁止重放。",
    "team_archive": "经原生管理审批删除团队，实际沿用平台归档：归档团队及其成员 Agent、封存成员全部会话、删除团队全部归属群聊，移除成员在其他群聊的关联，并按原生规则解散因此变空的群聊。主关联群聊 ID 不是全部影响范围。须先读 team_archive_preview，并原样绑定 fingerprint、全部 memberAgentIds 和 linkedChatRoomId；需要 teams:archive 与 agents:archive 授权，拒绝系统/归档团队及原生忙碌状态。OPERATION_UNCONFIRMED 可能已有部分级联副作用，须核查，禁止重放。",
}
