const styles = {
  selectedDetailFrame:
    "grid w-full max-w-[1280px] min-w-0 [justify-self:center] [align-content:start] [gap:8px]",
  overviewLayout:
    "grid min-w-0 [grid-template-columns:minmax(0,_1fr)_minmax(280px,_320px)] [align-items:start] [gap:8px] max-[1180px]:[grid-template-columns:1fr]",
  overviewMain: "grid min-w-0 [align-content:start] [gap:8px]",
  overviewAside: "grid min-w-0 [align-content:start] [gap:8px]",
  paneContent: "grid min-w-0 [align-content:start] [gap:8px]",
} as const;

export default styles;
