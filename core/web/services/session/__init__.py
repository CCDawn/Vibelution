"""Session service internal slices (Chat/Coding hot path).

Stage 2 modules (claim scopes):

- ``list_cache`` — session list index cache
- ``live_output`` — live overlay state + checkpoint I/O
- ``journal_bridge`` — conversation events cache / append / ledger seq
- ``submit`` — submit / guidance / edit-resubmit entrypoints
- ``schedule`` — queue / executor handoff
- ``stream_capture`` — UI capture batching + hooks
- ``worker`` — ``_run_session_turn`` + continuation loop
- ``persist`` — turn result / failure writers

Public callers should keep importing from ``core.web.services.session_service``
(facade re-exports). See ``README.md``.
"""
