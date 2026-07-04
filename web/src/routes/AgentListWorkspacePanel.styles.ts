const styles = {
  agentPanel: "min-w-0 min-h-0 [grid-template-rows:auto_auto_minmax(0,_1fr)] max-[1040px]:min-h-0 max-[860px]:[min-height:240px]",
  agentPanelCreating: "[grid-template-rows:auto_minmax(360px,_1.4fr)_minmax(120px,_0.6fr)] max-[1040px]:[grid-template-rows:auto_minmax(410px,_1fr)_minmax(96px,_0.28fr)]",
} as const;

export default styles;
