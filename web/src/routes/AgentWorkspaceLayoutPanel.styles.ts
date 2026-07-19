const styles = {
  // Path B Wave1: list rail scales with viewport so detail no longer feels like a dead right void.
  workspace:
    "grid h-full min-h-0 [grid-template-columns:clamp(340px,_26vw,_420px)_minmax(0,_1fr)] [gap:var(--agent-density-gap)] [padding:6px_10px_9px] max-[860px]:[grid-template-columns:1fr] max-[860px]:[align-content:start] max-[860px]:[overflow:auto]",
  directory:
    "grid min-h-0 min-w-0 [grid-template-rows:minmax(158px,_0.34fr)_minmax(280px,_0.66fr)] [gap:var(--agent-density-gap)] max-[860px]:[grid-template-rows:minmax(150px,_auto)_minmax(260px,_auto)]",
  workspaceCreating:
    "[grid-template-columns:minmax(0,_1fr)] [align-content:start] [overflow:auto]",
  createWorkspace:
    "grid min-h-full min-w-0 w-full [max-width:1180px] [margin:0_auto] [align-content:start] [padding:2px_0_10px]",
} as const;

export default styles;
