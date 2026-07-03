# Supervised Evolution Workspace Layout Design

## Goal

The supervised evolution page should behave like a compact operations workspace. In the first viewport, the user should see what can be launched, what is currently running or recently closed, and what evidence or next action is available.

## Chosen Approach

Use a restrained workspace refactor instead of a broad route rewrite:

- Keep the top workflow control as a slim stepper, not a card rail.
- Keep launch/source controls in the left rail.
- Let the center panel show a run overview, evidence, and next action when no case transcript exists.
- Show the transcript only when the selected workflow step has visible messages.
- Make the right live monitor dense and remove nested evidence cards inside cards.

## Component Boundaries

- `SupervisedWorkspaceTabs` owns only workflow navigation.
- `EvolutionRoute` continues to own data fan-in for this round.
- `EvolutionRoute.styles` owns layout geometry and card flattening.
- Existing supervised runtime/worktree authority is unchanged.

## Data Flow

The current worktree-run model remains the source for live supervised state. The layout reads the same `monitoredRun`, `supervisedWorkflowCards`, `supervisedClosedLoopRecord`, selected workflow step, and conversation messages that the page already derives.

When `selectedWorkflowConversationMessages` is empty, the center panel renders an overview fallback built from the selected step, monitored run, task summary, live preview, closed-loop record, and next action metadata.

## Error And Empty States

Empty case IO is not treated as an empty page. It becomes a compact evidence workspace that explains the selected phase, shows live or closed-loop evidence if present, and keeps the next user action visible.

## Testing

Update the existing supervised layout tests so they protect the new contract:

- the workflow control is a compact stepper, not a fixed-width four-card rail;
- old duplicate workflow card wall styles are removed or flattened;
- the center panel has an overview fallback when transcript messages are absent;
- the existing active-run data path and worktree-run action path remain intact.

## Out Of Scope

- Backend supervised evolution behavior.
- Worktree-run authority, action APIs, or runtime-scene logging.
- Full component extraction from `EvolutionRoute`.
- Project-memory semantic rewrites beyond the final task update.
