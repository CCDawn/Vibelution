# Knowledge Collection One-Click Design

## Confirmed Behavior

- The knowledge collection phase card owns the one-click action for completing the whole collection flow.
- The knowledge steward stage card stays single-purpose: it only starts or opens the steward review agent task.
- The one-click action resumes from the current phase state instead of replacing per-stage controls.

## UI Contract

- On the three-phase research console, the `knowledge_collection` phase card shows a distinct `一键完成知识搜集` action.
- The stage detail view keeps the memory/steward stage action scoped to steward review, such as `通知知识库管理员`.
- The steward stage action must not call the whole-phase one-click completion path.

## Backend Contract

- The whole-phase action is exposed through a dedicated workflow orchestration endpoint.
- The endpoint starts a background completion run and returns an accepted work-run payload.
- Existing per-stage agent private-chat task execution remains available and unchanged.

## Verification

- Frontend layout tests must prove the phase card contains the one-click action and the memory stage remains agent-task scoped.
- Backend route tests must prove the new endpoint delegates to the orchestration service with `backgroundExecution`.
