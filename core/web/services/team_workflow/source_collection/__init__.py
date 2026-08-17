"""Source-collection packs for Team workflow.

The D03 stage-1 knowledge collection single facade is the Agent-visible entry
point; it reuses the existing source-collection node/ledger/storage.
"""

from .facade import (
    FACADE_SCHEMA_VERSION,
    ResearchKnowledgeCollectionError,
    research_knowledge_collection_facade,
)

__all__ = [
    "FACADE_SCHEMA_VERSION",
    "ResearchKnowledgeCollectionError",
    "research_knowledge_collection_facade",
]