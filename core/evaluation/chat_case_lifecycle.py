# -*- coding: utf-8 -*-
"""Shared lifecycle metadata for chat-derived evaluation cases."""

from __future__ import annotations

from typing import Any

from .supervised_intake import (
    REVIEWED_CHAT_ALLOWED_DOWNSTREAM_USES,
    reviewed_chat_dataset_metadata as _reviewed_chat_dataset_metadata,
)


POSITIVE_DATASET_NAME = "chat_reviewed_multiturn"
POSITIVE_DATASET_BUNDLE_NAME = "chat_reviewed_multiturn_v1"
NEGATIVE_DATASET_NAME = "chat_negative_multiturn"
NEGATIVE_DATASET_BUNDLE_NAME = "chat_negative_multiturn_v1"

CHAT_CASE_ALLOWED_DOWNSTREAM_USES = list(REVIEWED_CHAT_ALLOWED_DOWNSTREAM_USES)


def chat_case_lifecycle_payload() -> dict[str, Any]:
    """Return the public API lifecycle contract for chat-derived cases."""

    return {
        "rawChatDirectTrainingAllowed": False,
        "candidateStage": "pending_review",
        "reviewedCaseStage": "reviewed_chat_case",
        "datasetTarget": POSITIVE_DATASET_NAME,
        "negativeTarget": NEGATIVE_DATASET_NAME,
        "allowedDownstreamUses": list(CHAT_CASE_ALLOWED_DOWNSTREAM_USES),
    }


def chat_reviewed_dataset_metadata() -> dict[str, Any]:
    """Return registry metadata for the reviewed positive chat dataset."""

    return _reviewed_chat_dataset_metadata()


__all__ = [
    "CHAT_CASE_ALLOWED_DOWNSTREAM_USES",
    "NEGATIVE_DATASET_BUNDLE_NAME",
    "NEGATIVE_DATASET_NAME",
    "POSITIVE_DATASET_BUNDLE_NAME",
    "POSITIVE_DATASET_NAME",
    "chat_case_lifecycle_payload",
    "chat_reviewed_dataset_metadata",
]
