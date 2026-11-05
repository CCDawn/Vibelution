"""Finite Agent configuration contracts; importing schemas never opens an owner."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Reference = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
ModelReference = Annotated[str, Field(min_length=1, max_length=200)]
# Native profile prose is limited by line count, not total characters. The
# management asset projection owns pagination; GET must preserve legal prose.
Text = str


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentConfigurationQuery(Closed):
    agent_id: Reference


class PersonaProfile(Closed):
    gender: Text | None = None
    age: Text | None = None
    pronouns: Text | None = None
    personality: Text | None = None
    communicationStyle: Text | None = None
    background: Text | None = None
    collaborationPreference: Text | None = None
    identityNotes: Text | None = None
    expertise: list[Text] | None = Field(default=None, max_length=12)


class TaskProfile(Closed):
    mission: Text | None = None
    responsibilities: Text | None = None
    preferredTasks: Text | None = None
    avoidTasks: Text | None = None
    successCriteria: Text | None = None
    deliverables: Text | None = None
    constraints: Text | None = None
    handoffNotes: Text | None = None
    taskTypes: list[Text] | None = Field(default=None, max_length=16)


class CompressionLevels(Closed):
    light: float = Field(ge=0, le=1)
    standard: float = Field(ge=0, le=1)
    deep: float = Field(ge=0, le=1)
    emergency: float = Field(ge=0, le=1)


class CompressionSummaryChars(Closed):
    light: int = Field(ge=1, le=20000)
    standard: int = Field(ge=1, le=20000)
    deep: int = Field(ge=1, le=20000)
    emergency: int = Field(ge=1, le=20000)


class CompressionPreservation(Closed):
    keepAiMessages: int = Field(ge=1, le=50)
    preserveErrors: bool
    extractKeyDecisions: bool
    retentionFocus: list[str] | None = None


class CompressionPolicy(Closed):
    # The native writer requires an explicit policy. There is no inheritance
    # reset operation for newly materialized Agents.
    mode: Literal["custom"]
    enabled: bool
    maxTokenLimit: int = Field(ge=1, le=2000000)
    maxCompressionsPerSession: int = Field(ge=1, le=100)
    levels: CompressionLevels
    summaryChars: CompressionSummaryChars
    preservation: CompressionPreservation
    policyVersion: int = Field(default=0, ge=0, le=1000000)
    compressionTriggerTokenLimit: int = Field(default=0, ge=0, le=2000000)
    postCompressionTargetTokenLimit: int = Field(default=0, ge=0, le=2000000)


class ModelParameters(Closed):
    expected_model_ref: ModelReference
    context_window: int = Field(gt=0)
    reasoning_effort: str = Field(max_length=80)

    @field_validator("expected_model_ref", "reasoning_effort")
    @classmethod
    def canonical_text(cls, value):
        if value != value.strip() or len(value.splitlines()) > 1:
            raise ValueError("Use a canonical single-line parameter")
        return value


class BudgetParameters(Closed):
    # Explicit null clears; omitted is not a reset. 0 means unlimited.
    maxCallsPerTurn: int | None = Field(ge=0, le=200)


class CompressionParameters(Closed):
    policy: CompressionPolicy


class AgentParametersUpdate(AgentConfigurationQuery):
    expected_config_revision: int = Field(ge=0)
    kind: Literal["model", "budget", "compression"]
    parameters: ModelParameters | BudgetParameters | CompressionParameters

    @model_validator(mode="after")
    def one_parameter_owner(self):
        expected = {"model": ModelParameters, "budget": BudgetParameters, "compression": CompressionParameters}
        if not isinstance(self.parameters, expected[self.kind]):
            raise ValueError("Parameter block must match kind")
        return self


class ModelStored(Closed):
    contextWindow: int | None = Field(ge=0)
    reasoningEffort: str | None = Field(max_length=80)
    legacyReasoningEffort: str | None = Field(max_length=80)


class ModelEffective(Closed):
    available: bool
    contextWindow: int | None = Field(ge=0)
    reasoningEffort: str | None = Field(max_length=80)


class ModelOrigins(Closed):
    contextWindow: str = Field(max_length=80)
    reasoningEffort: Literal["native_runtime", "unavailable"]


class ModelLimits(Closed):
    minContextWindow: Literal[1] = 1
    maxContextWindow: int | None = Field(ge=0)
    reasoningEffortValues: list[Annotated[str, Field(max_length=80)]] = Field(max_length=32)
    reasoningEffortReset: Literal[""] = ""
    contextWindowResetSupported: Literal[False] = False


class ModelParameterView(Closed):
    modelRef: ModelReference
    stored: ModelStored
    effective: ModelEffective
    origin: ModelOrigins
    limits: ModelLimits


class BudgetValue(Closed):
    maxCallsPerTurn: int | None = Field(ge=0, le=200)


class BudgetEffective(Closed):
    available: bool
    maxCallsPerTurn: int | None = Field(ge=0)


class BudgetLimits(Closed):
    minimum: Literal[1] = 1
    maximum: Literal[200] = 200
    unlimited: Literal[0] = 0
    clearToDefault: Literal[True] = True


class BudgetDeclaredPolicy(Closed):
    maxCallsPerTurn: int | None = Field(ge=0)
    maxCallsPerTurnByModelFamily: dict[Literal["deepseek", "claude", "openai", "gemini", "qwen", "llama", "mistral", "default"], Annotated[int, Field(ge=0)]] = Field(max_length=8)


class BudgetParameterView(Closed):
    stored: BudgetValue
    effective: BudgetEffective
    origin: Literal["agent_override", "family_or_base_unavailable"]
    limits: BudgetLimits
    declaredPolicy: BudgetDeclaredPolicy


class CompressionEffective(Closed):
    available: bool
    source: str = Field(max_length=80)
    enabled: bool | None
    effectiveTokenLimit: int | None = Field(ge=0)
    compressionTriggerTokenLimit: int | None = Field(ge=0)
    postCompressionTargetTokenLimit: int | None = Field(ge=0)
    contextWindowLimit: int | None = Field(ge=0)


class CompressionParameterView(Closed):
    stored: CompressionPolicy | None
    effective: CompressionEffective
    origin: Literal["agent", "migration_required"]


class AgentParameterViews(Closed):
    model: ModelParameterView
    budget: BudgetParameterView
    compression: CompressionParameterView


class AgentConfigurationResponse(Closed):
    source: Literal["native-agent-configuration"] = "native-agent-configuration"
    untrustedContent: Literal[True] = True
    agentId: Reference
    configRevision: int = Field(ge=0)
    agentUpdatedAt: str = Field(min_length=1, max_length=160)
    compiledMatches: bool
    displayName: str = Field(min_length=1, max_length=120)
    dialogueModelId: ModelReference
    promptTemplateId: str = Field(max_length=160)
    personaProfile: PersonaProfile
    taskProfile: TaskProfile
    parameters: AgentParameterViews

    @field_validator("untrustedContent", mode="before")
    @classmethod
    def explicit_untrusted(cls, value):
        if value is not True:
            raise ValueError("Explicit untrusted marker required")
        return value
