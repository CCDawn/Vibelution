const styles = {
  agentPanel: "min-w-0 min-h-0 max-[1040px]:min-h-0 max-[860px]:[min-height:240px]",
  agentPanelIdle: "[grid-template-rows:auto_minmax(0,_1fr)]",
  agentPanelSelecting: "[grid-template-rows:auto_auto_minmax(0,_1fr)]",
} as const;

export default styles;
