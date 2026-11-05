"""Closed discovery and Agent-local prompt edits, without global prompt mutation."""
from __future__ import annotations

import json
from typing import Annotated, Literal
from pydantic import Field, field_validator, field_serializer
from .asset_contracts import Closed, Reference, Fingerprint, ToolPolicyPatch, ToolPolicyResponse

ContentHash = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class AgentPromptQuery(Closed):
    agent_id: Reference


class PromptTemplateCandidate(Closed):
    templateId: str
    name: str
    category: str
    status: str
    contentHash: ContentHash | None
    contentLength: int | None
    contentAvailable: bool
    origin: Literal["record_content", "source_file", "empty"]


class PromptTemplateView(PromptTemplateCandidate):
    content: str
    contentHash: ContentHash
    contentLength: int
    contentAvailable: Literal[True]


class AgentPromptResponse(Closed):
    agentId: Reference
    configRevision: int
    template: PromptTemplateView
    # Lightweight choices only; actual bodies use the selected Agent view.
    candidates: list[PromptTemplateCandidate]
    activation: Literal["next_submission"] = "next_submission"
    editScope: Literal["single_agent_copy_on_write"] = "single_agent_copy_on_write"
    untrustedContent: Literal[True] = True


class AgentPromptUpdate(AgentPromptQuery):
    expected_config_revision: int = Field(ge=0)
    expected_template_id: Reference
    expected_content_hash: ContentHash
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Empty prompt")
        return value


class ToolPolicyInspectQuery(AgentPromptQuery):
    # A single encoded, bounded DTO keeps GET discovery separate from writes.
    updates_json: str = Field(default="{}", max_length=12000)

    @field_validator("updates_json")
    @classmethod
    def closed_patch(cls, value):
        def unique(pairs):
            output = {}
            for key, item in pairs:
                if key in output:
                    raise ValueError("Duplicate policy field")
                output[key] = item
            return output
        parsed = json.loads(value, object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid JSON constant")))
        if parsed != {}:
            ToolPolicyPatch.model_validate(parsed)
        elif not isinstance(parsed, dict):
            raise ValueError("Expected policy object")
        return value


class ToolCandidate(Closed):
    name: str
    description: str
    available: bool


class PolicyValidation(Closed):
    valid: bool
    errors: list[str]
    warnings: list[str]


class PolicyPreview(Closed):
    visibleTools: list[str]
    executableTools: list[str]
    preferredTools: list[str]
    blockedTools: list[str]
    unavailableTools: list[str]
    unknownTools: list[str]
    approvalRequiredTools: list[str]


class ToolPolicyInspectResponse(Closed):
    agentId: Reference
    current: ToolPolicyResponse
    proposedPolicy: ToolPolicyPatch
    proposedPolicyFingerprint: Fingerprint
    validation: PolicyValidation
    preview: PolicyPreview
    candidates: list[ToolCandidate]
    affectedAgentCount: int
    confirmationRequired: bool
    confirmationReasons: list[str]
    untrustedContent: Literal[True] = True

    @field_serializer("proposedPolicy")
    def serialize_policy(self, value):
        return value.model_dump(exclude_none=True)
