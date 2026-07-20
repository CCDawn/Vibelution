"""Team workflow internal packs (research / SC / experiment / loop).

Stage 3 claim packs (partial):

- ``orchestration_core`` — get/ensure orchestration document
- ``source_collection.candidates`` — candidate register/import/extract/list
- pre-existing: ``source_collection_*`` helpers, ``research_memory_context``

Public callers should import from ``team_workflow_orchestration_service``
(facade re-exports). See ``README.md``.
"""
