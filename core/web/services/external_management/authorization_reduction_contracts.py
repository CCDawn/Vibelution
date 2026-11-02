"""Closed self-subject authorization reduction/revocation contracts."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .asset_contracts import Closed


def _scope_schema(schema):
    # Late binding keeps this DTO safe to register from contracts.py itself.
    from .contracts import SCOPES
    schema.setdefault("items", {})["enum"] = list(SCOPES)
    schema["uniqueItems"] = True


def _scopes(value, *, empty=False):
    from .contracts import SCOPES
    if (not isinstance(value, list) or not empty and not value
            or any(type(scope) is not str or scope not in SCOPES for scope in value)
            or value != sorted(set(value))):
        raise ValueError("Scopes must be explicit, sorted, unique registered names")
    return value


class AuthorizationRevoke(Closed):
    expected_scopes: list[str] = Field(min_length=1, max_length=128, json_schema_extra=_scope_schema)
    expected_grant_revision: int = Field(ge=0, le=9_007_199_254_740_990)

    @field_validator("expected_scopes")
    @classmethod
    def sorted_scopes(cls, value):
        return _scopes(value)


class AuthorizationReduce(AuthorizationRevoke):
    remove_scopes: list[str] = Field(min_length=1, max_length=128, json_schema_extra=_scope_schema)

    @field_validator("remove_scopes")
    @classmethod
    def sorted_removals(cls, value):
        return _scopes(value)

    @model_validator(mode="after")
    def strict_reduction(self):
        if not set(self.remove_scopes) < set(self.expected_scopes):
            raise ValueError("Remove only currently granted scopes; use authorization_revoke to remove all")
        return self


class AuthorizationReductionResult(Closed):
    subjectId: str = Field(pattern=r"^ops-[a-f0-9]{32}$")
    previousScopes: list[str] = Field(min_length=1, max_length=128, json_schema_extra=_scope_schema)
    removedScopes: list[str] = Field(min_length=1, max_length=128, json_schema_extra=_scope_schema)
    scopes: list[str] = Field(max_length=128, json_schema_extra=_scope_schema)
    grantRevision: int = Field(ge=1)
    revoked: bool

    @field_validator("previousScopes", "removedScopes", "scopes")
    @classmethod
    def known_scopes(cls, value):
        return _scopes(value, empty=True)

    @model_validator(mode="after")
    def exact_remaining_scopes(self):
        if (not set(self.removedScopes).issubset(self.previousScopes)
                or self.scopes != sorted(set(self.previousScopes) - set(self.removedScopes))
                or self.revoked != (not self.scopes)):
            raise ValueError("Effective authorization must match the exact removal")
        return self


class AuthorizationReductionResponse(Closed):
    action: Literal["authorization_reduce", "authorization_revoke"]
    requestId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
    status: Literal["completed", "unknown"]
    verified: bool
    reused: bool = False
    authorization: AuthorizationReductionResult | None = None

    @model_validator(mode="after")
    def completion_proof(self):
        if (self.status == "completed") != (self.verified and self.authorization is not None):
            raise ValueError("Completion requires an atomic native authorization proof")
        if self.status == "unknown" and (self.verified or self.authorization is not None):
            raise ValueError("Unknown state cannot claim an authorization result")
        if self.authorization is not None and self.authorization.revoked != (self.action == "authorization_revoke"):
            raise ValueError("Receipt action must match native revocation")
        return self


AUTHORIZATION_REDUCTION_MODELS = {"authorization_reduce": AuthorizationReduce, "authorization_revoke": AuthorizationRevoke}
AUTHORIZATION_REDUCTION_SCOPES = {name: None for name in AUTHORIZATION_REDUCTION_MODELS}
AUTHORIZATION_REDUCTION_HELP = {
    "authorization_reduce": "经原生高风险逐次审批，仅减少当前已认证operator主体的显式scope；先authorization_status取得排序后的expected_scopes和expected_grant_revision，remove_scopes必须非空且保留至少一个scope，移除全部应使用authorization_revoke。需稳定request_id，不可传其他subject、actor或force。scope、版本和回执在原生主体记录中原子持久化，旧回执不恢复已移除权限。",
    "authorization_revoke": "经原生高风险逐次审批，撤销当前已认证operator主体全部有效授权；先authorization_status取得expected_scopes和expected_grant_revision，使用稳定request_id。完成后原凭据立即失效，只能复核这一次authorization_revoke管理回执，不能业务查询、再升级或新降权；历史记录保留。unknown只查原回执，不换主体或请求ID重放。",
}
