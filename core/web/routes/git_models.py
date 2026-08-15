"""Public contracts for Git workbench JSON routes.

Known identity and status envelope fields stay explicit for OpenAPI. Nested
upstream, commit, worktree, and preview payloads still evolve, so extras pass
through. Routes must use response_model_exclude_unset=True.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GitCommitMessagePayload(BaseModel):
    paths: list[str] = Field(default_factory=list)
    model_id: str = Field(default="", alias="modelId")


class GitCommitPayload(BaseModel):
    paths: list[str] = Field(default_factory=list)
    message: str = ""


class GitCommitMessageModelPayload(BaseModel):
    model_id: str = Field(default="", alias="modelId")


class GitCommitMessagePromptPayload(BaseModel):
    prompt: str = ""


class GitStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    available: bool = False
    error: str = ""
    branch: str = ""
    headRev: str = ""
    headRevShort: str = ""
    upstream: dict[str, Any] | None = None
    snapshotId: str = ""
    createdAt: str = ""
    dirty: bool = False
    requiresAttention: bool = False
    statusLevel: str = ""
    summary: str = ""
    counts: dict[str, Any] | None = None
    localCommits: dict[str, Any] | None = None
    worktrees: dict[str, Any] | None = None
    files: list[dict[str, Any]] = Field(default_factory=list)
    totalFiles: int = 0
    truncated: bool = False


class GitCommitListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    available: bool = False
    error: str = ""
    commits: list[dict[str, Any]] = Field(default_factory=list)


class GitFileDiffResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    available: bool = False
    error: str = ""
    path: str = ""
    status: str = ""
    statusLabel: str = ""
    summary: str = ""
    diff: str = ""
    content: str = ""
    language: str = ""
    truncated: bool = False
    binary: bool = False


class GitObjectDetailResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    available: bool = False
    error: str = ""
    kind: str = ""
    ref: str = ""
    path: str = ""
    status: str = ""
    statusLabel: str = ""
    summary: str = ""
    diff: str = ""
    content: str = ""
    language: str = ""
    truncated: bool = False
    binary: bool = False
    meta: dict[str, Any] | None = None


class GitCommitMessageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str = ""
    modelId: str = ""
    prompt: str = ""
    files: list[str] = Field(default_factory=list)
    diffSummary: str = ""


class GitCommitMessageModelResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    modelId: str = ""
    previousModelId: str = ""


class GitCommitMessagePromptResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt: str = ""
    previousPromptChars: int = 0
    promptChars: int = 0


class GitCommitResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    committed: bool = False
    commitSha: str = ""
    shortSha: str = ""
    summary: str = ""
    files: list[str] = Field(default_factory=list)
