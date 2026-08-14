"""Team knowledge domain constants and ingestion catalogs.

Claim scope: source types, ingestion adapters, review enums, search modes,
and BM25/search token patterns. Mutable locks stay on team_knowledge_service.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = 1
SOURCE_TYPES = {
    "team_chat_refinement",
    "external_search_refinement",
    "pdf_refinement",
    "agent_authored",
    "runtime_evidence_refinement",
    "manual_user_entry",
}
INGESTION_ADAPTERS = {
    "team_chat_refinement": {
        "label": "Team chat refinement",
        "requiredSourceRef": ["roomId", "messageRange|roundId"],
        "optionalSourceRef": ["teamId", "threadId"],
        "evidenceKinds": ["message_range", "round"],
    },
    "external_search_refinement": {
        "label": "External search refinement",
        "requiredSourceRef": ["url|query"],
        "optionalSourceRef": ["retrievedAt", "searchEngine", "rank"],
        "evidenceKinds": ["url", "query", "excerpt"],
    },
    "pdf_refinement": {
        "label": "PDF refinement",
        "requiredSourceRef": ["filePath|url"],
        "optionalSourceRef": ["pageRange", "documentHash"],
        "evidenceKinds": ["file", "page_range", "excerpt"],
    },
    "agent_authored": {
        "label": "Agent authored",
        "requiredSourceRef": ["agentId"],
        "optionalSourceRef": ["sessionId", "turnId"],
        "evidenceKinds": ["agent_note"],
    },
    "runtime_evidence_refinement": {
        "label": "Runtime evidence refinement",
        "requiredSourceRef": ["runtimeSceneId|runId"],
        "optionalSourceRef": ["logPath", "eventCode", "artifactPath"],
        "evidenceKinds": ["runtime_scene", "log_ref", "artifact"],
    },
    "manual_user_entry": {
        "label": "Manual user entry",
        "requiredSourceRef": ["note|title"],
        "optionalSourceRef": ["author", "context"],
        "evidenceKinds": ["manual_note"],
    },
}
REVIEW_ROLES = {"owner", "lead", "steward", "knowledge_steward", "source_ingestor", "coordinator"}
IMPORTANCE_LEVELS = {"low", "medium", "high", "critical"}
STABILITY_VALUES = {"temporary", "evolving", "stable", "deprecated"}
SCOPES = {"agent", "team", "project", "global"}
REVIEW_PRIORITIES = {"normal", "elevated", "urgent"}
SUGGESTION_STATUSES = {"pending", "applied", "rejected"}
KNOWLEDGE_OWNER_TYPES = {"team", "agent"}
SOURCE_INBOX_STATUSES = {"pending", "accepted", "rejected", "duplicate", "needs_more_context"}
SOURCE_REVIEW_DECISIONS = {"accepted", "rejected", "duplicate", "needs_more_context"}
CENTRAL_SOURCE_STATUSES = {"active", "archived", "superseded"}
KNOWLEDGE_SEARCH_MODES = {"exact", "semantic", "hybrid", "bm25"}
MAX_LOCAL_SOURCE_COPIES = 16
MAX_LOCAL_SOURCE_COPY_BYTES = 50 * 1024 * 1024
BM25_K1 = 1.5
BM25_B = 0.75
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_SEARCH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]")
