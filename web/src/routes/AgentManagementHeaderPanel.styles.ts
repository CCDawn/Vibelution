const styles = {
  controlStrip: "grid [grid-template-columns:auto_minmax(0,_1fr)] [align-items:center] [gap:8px] min-w-0 [padding:2px_12px_0] max-[1120px]:[grid-template-columns:1fr] max-[860px]:[grid-template-columns:1fr]",
  managementNav: "[margin:0] max-[1120px]:[justify-self:start]",
} as const;

export default styles;
