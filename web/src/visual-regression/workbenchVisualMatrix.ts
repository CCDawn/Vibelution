export type WorkbenchVisualTheme = "light" | "dark";
export type WorkbenchVisualBackground = "default" | "custom";
export type WorkbenchVisualViewport = "desktop" | "narrow";
export type WorkbenchVisualState = "dense" | "empty" | "error" | "blocker" | "destructive";

export type WorkbenchVisualScenario = {
  id: string;
  path: string;
  theme: WorkbenchVisualTheme;
  background: WorkbenchVisualBackground;
  viewport: {
    width: number;
    height: number;
  };
  state: WorkbenchVisualState;
  reviewFocus: string[];
  expectedEvidence: "screenshot";
};

export const WORKBENCH_VISUAL_ACCEPTANCE_CHECKLIST = [
  "background remains visible",
  "text remains readable",
  "1px thin-line borders",
  "quiet controls by default",
  "visible focus state",
  "clear destructive, error, and blocker states",
  "no card wall",
  "no full-page opaque route wrapper",
] as const;

export const WORKBENCH_VISUAL_REVIEW_PROTOCOL = [
  "Start the app with: cd web && npm run dev -- --host 127.0.0.1",
  "For each scenario, open the path, set the stored theme to the scenario theme, and use a custom background when background is custom.",
  "Capture a screenshot or attach an observation note for every scenario id.",
  "Reject the wave if a screenshot shows a card wall, opaque route wrapper, unreadable text, invisible focus, or muted destructive/error/blocker state.",
] as const;

export const WORKBENCH_VISUAL_SCENARIOS: WorkbenchVisualScenario[] = [
  {
    id: "home-light-default-desktop-empty",
    path: "/",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "empty",
    reviewFocus: ["AppShell background ownership", "route outlet empty/default state"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-light-default-desktop-dense",
    path: "/chat",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["conversation workspace hierarchy", "quiet toolbar and row density"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-dark-default-desktop-dense",
    path: "/chat",
    theme: "dark",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["dark smoke contrast", "focus and active conversation states"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-light-custom-desktop-dense",
    path: "/chat",
    theme: "light",
    background: "custom",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["custom background visibility", "readability overlay strength"],
    expectedEvidence: "screenshot",
  },
  {
    id: "supervised-light-default-desktop-blocker",
    path: "/supervised-evolution",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "blocker",
    reviewFocus: ["next action visibility", "blocker state prominence"],
    expectedEvidence: "screenshot",
  },
  {
    id: "supervised-light-custom-narrow-blocker",
    path: "/supervised-evolution",
    theme: "light",
    background: "custom",
    viewport: { width: 390, height: 844 },
    state: "blocker",
    reviewFocus: ["narrow viewport layout stability", "background-aware panels"],
    expectedEvidence: "screenshot",
  },
  {
    id: "agents-light-default-desktop-dense",
    path: "/agents",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["agent list/detail panel hierarchy", "status chip language"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-light-default-desktop-dense",
    path: "/memory",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["memory overview panel nesting", "metric/status chip consistency"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-light-custom-narrow-empty",
    path: "/memory",
    theme: "light",
    background: "custom",
    viewport: { width: 390, height: 844 },
    state: "empty",
    reviewFocus: ["empty state readability", "narrow route header actions"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-graph-light-default-desktop-dense",
    path: "/memory/graph",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "dense",
    reviewFocus: ["graph page special-layout exception", "generic chrome consistency"],
    expectedEvidence: "screenshot",
  },
  {
    id: "config-light-default-desktop-destructive",
    path: "/config",
    theme: "light",
    background: "default",
    viewport: { width: 1440, height: 960 },
    state: "destructive",
    reviewFocus: ["destructive action visibility", "quiet non-primary controls"],
    expectedEvidence: "screenshot",
  },
  {
    id: "config-dark-custom-desktop-error",
    path: "/config",
    theme: "dark",
    background: "custom",
    viewport: { width: 1440, height: 960 },
    state: "error",
    reviewFocus: ["error state contrast", "custom background overlay in dark smoke"],
    expectedEvidence: "screenshot",
  },
];

function sortedUnique<T extends string>(items: T[]): T[] {
  return Array.from(new Set(items)).sort();
}

export function summarizeWorkbenchVisualCoverage(scenarios: WorkbenchVisualScenario[]) {
  return {
    themes: sortedUnique(scenarios.map((scenario) => scenario.theme)),
    backgrounds: sortedUnique(scenarios.map((scenario) => scenario.background)),
    viewports: sortedUnique(scenarios.map((scenario) => (scenario.viewport.width < 700 ? "narrow" : "desktop"))),
    states: sortedUnique(scenarios.map((scenario) => scenario.state)),
    paths: sortedUnique(scenarios.map((scenario) => scenario.path)),
  };
}
