"""Pure request contract for run-scoped local integration authority."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator


class LocalIntegrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledge: StrictBool
    allowedFiles: list[StrictStr] = Field(min_length=1, max_length=8)
    teamId: StrictStr = Field(min_length=1, max_length=160)
    validForSeconds: StrictInt = Field(ge=60, le=3600)

    @field_validator("acknowledge")
    @classmethod
    def acknowledged(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Explicit local integration acknowledgement is required.")
        return value

    @field_validator("allowedFiles")
    @classmethod
    def exact_files(cls, value: list[str]) -> list[str]:
        from .self_evolution_candidate_target_contract import CandidateTargetContractError, normalize_target_files

        for item in value:
            raw = item.replace("\\", "/")
            if any(char in raw for char in "*?[]{}") or any(
                part in {"", ".", ".."} for part in raw.split("/")
            ):
                raise ValueError("allowedFiles requires exact repository-relative files.")
        try:
            return normalize_target_files(value)
        except CandidateTargetContractError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("teamId")
    @classmethod
    def team_id(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("teamId must be a nonempty exact Team id.")
        return value
