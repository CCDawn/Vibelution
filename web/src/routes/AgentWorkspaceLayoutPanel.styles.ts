const styles = {
  workspace:
    "grid h-full min-h-0 [grid-template-columns:minmax(238px,_300px)_minmax(0,_1fr)] [gap:var(--agent-density-gap)] [padding:6px_10px_9px] max-[860px]:[grid-template-columns:1fr] max-[860px]:[align-content:start] max-[860px]:[overflow:auto]",
  directory:
    "grid min-h-0 min-w-0 [grid-template-rows:minmax(158px,_0.34fr)_minmax(280px,_0.66fr)] [gap:var(--agent-density-gap)] max-[860px]:[grid-template-rows:minmax(150px,_auto)_minmax(260px,_auto)]",
  workspaceCreating:
    "max-[860px]:[grid-template-rows:minmax(0,_1fr)]",
} as const;

export default styles;
