"""Closed, metadata-only discovery contracts for native knowledge owners."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .asset_contracts import Closed, Fingerprint, Reference

KNOWLEDGE_CATALOG_SCOPES = ("knowledge:catalog:read",)
KNOWLEDGE_CATALOG_HELP = (
    "按owner_type(agent/team)、owner_id或query分页发现当前授权项目已有知识库元数据，"
    "包括可由当前operator管理的系统团队库；只返回owner、公开名称、状态、scopedKnowledgeBaseId及ACL fingerprint。"
    "不读取正文、不以Agent身份授权、不初始化缺失目录；partial/unavailable不能解释为没有知识库。"
    "续页必须原样携带expected_digest，目录变化后从首页重读；修改ACL先用精确scopedKnowledgeBaseId调用knowledge_acl_get。"
    "需独立knowledge:catalog:read，目录可见不等于正文或ACL写入授权。"
)


class KnowledgeCatalogQuery(Closed):
    owner_type: Literal["", "agent", "team"] = ""
    owner_id: str = Field(default="", max_length=160, pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.:-]*)?$")
    query: str = Field(default="", max_length=160)
    offset: int = Field(default=0, ge=0, le=10_000)
    limit: int = Field(default=6, ge=1, le=6)
    expected_digest: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")

    @model_validator(mode="after")
    def continuation(self):
        if self.owner_id and not self.owner_type:
            raise ValueError("owner_id requires owner_type")
        if self.offset and not self.expected_digest:
            raise ValueError("Continuation requires the original digest")
        return self


class KnowledgeCatalogEntry(Closed):
    knowledgeBaseId: Reference
    scopedKnowledgeBaseId: str = Field(max_length=330)
    ownerType: Literal["agent", "team"]
    ownerId: Reference
    name: str = Field(min_length=1, max_length=64)
    status: Literal["active", "archived"]
    fingerprint: Fingerprint

    @model_validator(mode="after")
    def canonical_owner(self):
        if self.scopedKnowledgeBaseId != f"{self.ownerType}:{self.ownerId}:{self.knowledgeBaseId}":
            raise ValueError("Catalog identity must match its native owner")
        return self


class KnowledgeCatalogResponse(Closed):
    knowledgeBases: list[KnowledgeCatalogEntry] = Field(max_length=6)
    status: Literal["available", "partial", "unavailable"]
    total: int = Field(ge=0, le=10_000)
    offset: int = Field(ge=0, le=10_000)
    nextOffset: int | None = Field(default=None, ge=0, le=10_000)
    digest: Fingerprint
    unavailableOwnerCount: int = Field(ge=0, le=10_000)
    issues: list[Literal["owner_authority_unavailable", "library_authority_unavailable", "unknown_library_owner"]] = Field(max_length=3)
    requiredScopes: list[Literal["knowledge:catalog:read"]] = Field(min_length=1, max_length=1)
    coverage: str = Field(max_length=360)
    untrustedContent: Literal[True] = True

    @model_validator(mode="after")
    def truthful_coverage_and_page(self):
        if ((self.status == "available") != (not self.issues)
                or self.status == "available" and self.unavailableOwnerCount
                or self.status == "unavailable" and self.total
                or self.status == "partial" and not self.total):
            raise ValueError("Catalog status must match verified coverage")
        ids = [row.scopedKnowledgeBaseId for row in self.knowledgeBases]
        end = self.offset + len(ids)
        if (len(ids) != len(set(ids)) or len(ids) > max(0, self.total - self.offset)
                or self.nextOffset is not None and (not ids or self.nextOffset != end or end >= self.total)
                or self.nextOffset is None and ids and end < self.total):
            raise ValueError("Catalog continuation must match the complete returned rows")
        return self
