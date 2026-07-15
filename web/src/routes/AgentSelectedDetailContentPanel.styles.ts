const styles = {
  selectedDetailFrame:
    "grid w-full min-w-0 [align-content:start] [gap:8px]",
  overviewLayout:
    "grid min-w-0 [grid-template-columns:minmax(0,_4fr)_minmax(300px,_1fr)] [align-items:start] [gap:8px] max-[1280px]:[grid-template-columns:minmax(0,_1fr)_minmax(280px,_320px)] max-[1040px]:[grid-template-columns:1fr]",
  overviewMain: "grid min-w-0 [align-content:start] [gap:8px]",
  overviewAside: "grid min-w-0 [align-content:start] [gap:8px]",
  paneContent: "grid min-w-0 [align-content:start] [gap:8px]",
} as const;

export default styles;
