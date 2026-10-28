"""Exact, displayable write-dispatch arguments shared by execution and approval."""
from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_WRITE_TASK_CHARS = 12000


class DispatchWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    project_id: str = Field(min_length=1, max_length=160)
    agent_id: str = Field(min_length=1, max_length=160)
    dispatch_id: str = Field(min_length=1, max_length=120)
    task: str = Field(min_length=1, max_length=MAX_WRITE_TASK_CHARS)

    @field_validator("project_id", "agent_id", "dispatch_id")
    @classmethod
    def displayable_id(cls, value: str, info):
        pattern = r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}" if info.field_name == "dispatch_id" else r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}"
        if re.fullmatch(pattern, value) is None:
            raise ValueError("Identity cannot be displayed safely")
        return value

    @field_validator("task")
    @classmethod
    def displayable_task(cls, value: str):
        if (value != value.strip() or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"}
                and char not in "\n\t" for char in value)):
            raise ValueError("Task cannot be displayed safely")
        return value


def dispatch_write_approval_summary(parameters: dict) -> dict:
    values = DispatchWrite.model_validate(parameters)
    return {
        "assistantAction": "dispatch_write",
        "assistantTargets": {"project_id": values.project_id, "agent_id": values.agent_id,
                             "dispatch_id": values.dispatch_id},
        "assistantRequestedPermission": "workspace_write",
        "assistantTask": values.task,
    }
