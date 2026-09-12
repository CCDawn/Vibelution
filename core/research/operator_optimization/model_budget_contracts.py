"""Explicit, currency-aware upper bounds for operator discussion admission."""
from typing import Literal

from pydantic import Field

from .candidate import Contract, Identity


class OperatorModelPrice(Contract):
    modelRef: str = Field(min_length=3, max_length=256)
    priceVersion: Identity
    currency: Literal["CNY", "USD"]
    inputPerMillion: float = Field(ge=0)
    outputPerMillion: float = Field(ge=0)


class OperatorDiscussionBudget(Contract):
    tokenLimit: int = Field(ge=1, strict=True)
    maxOutputTokensPerCall: int = Field(ge=1, strict=True)
    maxCalls: int = Field(ge=2, strict=True)
    prices: tuple[OperatorModelPrice, ...] = Field(min_length=1)
