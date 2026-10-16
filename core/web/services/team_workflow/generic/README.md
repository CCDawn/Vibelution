# User-defined team workflows

The service is the sole flow/run state owner. The existing Team namespace supplies formal/developer storage roots; atomic JSON snapshots and cross-process locks enforce revisions. User definitions and each run's frozen copy are distinct. New HTTP endpoints are additive version-one contracts and do not modify retained research routes or require a question ID.

- `models.py`: bounded public contracts, unique field/step IDs and input validation.
- `store.py`: Team authority, validated path components, atomic writes and CAS locks.
- `service.py`: explicit run commands, sequential transitions, frozen inputs and durable dispatch receipts. An assigned output executes its configured Agent; an unassigned output delivers prior results.
- `native.py`: existing Agent-scoped hidden workspace Sessions, stable create/submission identity, canonical completion and verified restart-resume chains. Stop targets the effective Turn. Only references and lifecycle records are stored; Session remains transcript authority.
- `runtime.py`: one owned reconciliation worker. Reads do not dispatch. Startup waits for native Session recovery; delayed callbacks are fenced by the lifespan stop flag under the admission lock. Shutdown closes this producer before native Session workers.

Retry may create a new attempt only after canonical evidence permits it. Unknown Session identity or active-state uncertainty fails visibly and prevents duplicate execution or false stop success. Flow/run lists remain readable while execution is warming; artifact projection waits for the owner. Membership and Agent availability are checked again before dispatch. No raw model invocation or changes to ordinary Session core are introduced.

Tests use temporary Team storage and a substituted native port. Those tests prove orchestration and adapters, not real model output quality or a live application's restart acceptance.
