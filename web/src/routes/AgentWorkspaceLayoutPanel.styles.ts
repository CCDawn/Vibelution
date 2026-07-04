const styles = {
  workspace:
    "grid [grid-template-columns:minmax(214px,_268px)_minmax(430px,_1.08fr)_minmax(330px,_0.86fr)] [gap:var(--agent-density-gap)] min-h-0 [padding:6px_10px_9px] max-[1040px]:[grid-template-columns:minmax(220px,_270px)_minmax(0,_1fr)] max-[1040px]:[grid-auto-rows:minmax(180px,_auto)] max-[1040px]:[overflow:auto] max-[860px]:[grid-template-columns:1fr] max-[860px]:[grid-auto-rows:auto] max-[860px]:[align-content:start] max-[860px]:min-h-0 max-[860px]:[overflow:auto]",
  workspaceCreating:
    "max-[1040px]:[grid-template-rows:minmax(0,_1fr)]",
} as const;

export default styles;
