"""Team workflow internal packs (research / SC / experiment / loop).

Stage 3 claim packs (partial):

- ``orchestration_core`` — get/ensure orchestration document
- ``source_collection.candidates`` — candidate register/import/extract/list
- ``source_collection.runs`` — start run / search execute / summary
- ``source_collection.stages`` — stage session task start/writeback/context/reconcile
- ``source_collection.storage`` — open storage target
- pre-existing: ``source_collection_*`` helpers, ``research_memory_context``

Public callers should import from ``team_workflow_orchestration_service``
(facade re-exports). See ``README.md``.
"""
