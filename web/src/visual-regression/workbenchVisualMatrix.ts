export type WorkbenchVisualTheme = "light" | "dark";
export type WorkbenchVisualBackground = "default" | "custom";
export type WorkbenchVisualViewport = "compact" | "standard" | "wide";
export type WorkbenchVisualState = "dense" | "empty" | "error" | "blocker" | "destructive";

export const WORKBENCH_DESKTOP_VIEWPORTS = {
  compact: { width: 1280, height: 720 },
  standard: { width: 1440, height: 900 },
  wide: { width: 1920, height: 1080 },
} as const;

export function classifyWorkbenchVisualViewport(width: number): WorkbenchVisualViewport {
  if (width >= WORKBENCH_DESKTOP_VIEWPORTS.wide.width) {
    return "wide";
  }
  if (width <= WORKBENCH_DESKTOP_VIEWPORTS.compact.width) {
    return "compact";
  }
  return "standard";
}

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
  "Start the app through Vibelution Launcher; use a scoped Vite dev server only when Launcher cannot render the task branch before integration.",
  "For each scenario, open the path, set the stored theme to the scenario theme, and use a custom background when background is custom.",
  "Capture a screenshot or attach an observation note for every scenario id.",
  "Reject the wave if a screenshot shows a card wall, opaque route wrapper, unreadable text, invisible focus, or muted destructive/error/blocker state.",
] as const;

const compact = WORKBENCH_DESKTOP_VIEWPORTS.compact;
const standard = WORKBENCH_DESKTOP_VIEWPORTS.standard;
const wide = WORKBENCH_DESKTOP_VIEWPORTS.wide;

export const WORKBENCH_VISUAL_SCENARIOS: WorkbenchVisualScenario[] = [
  {
    id: "home-light-default-standard-empty",
    path: "/",
    theme: "light",
    background: "default",
    viewport: standard,
    state: "empty",
    reviewFocus: ["AppShell background ownership", "route outlet empty/default state"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-light-default-compact-dense",
    path: "/chat",
    theme: "light",
    background: "default",
    viewport: compact,
    state: "dense",
    reviewFocus: ["conversation workspace hierarchy", "quiet toolbar and row density"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-dark-default-standard-dense",
    path: "/chat",
    theme: "dark",
    background: "default",
    viewport: standard,
    state: "dense",
    reviewFocus: ["dark smoke contrast", "focus and active conversation states"],
    expectedEvidence: "screenshot",
  },
  {
    id: "chat-light-custom-wide-dense",
    path: "/chat",
    theme: "light",
    background: "custom",
    viewport: wide,
    state: "dense",
    reviewFocus: ["custom background visibility", "readability overlay strength"],
    expectedEvidence: "screenshot",
  },
  {
    id: "supervised-light-default-standard-blocker",
    path: "/supervised-evolution",
    theme: "light",
    background: "default",
    viewport: standard,
    state: "blocker",
    reviewFocus: ["next action visibility", "blocker state prominence"],
    expectedEvidence: "screenshot",
  },
  {
    id: "supervised-light-custom-compact-blocker",
    path: "/supervised-evolution",
    theme: "light",
    background: "custom",
    viewport: compact,
    state: "blocker",
    reviewFocus: ["narrow viewport layout stability", "background-aware panels"],
    expectedEvidence: "screenshot",
  },
  {
    id: "agents-light-default-standard-dense",
    path: "/agents",
    theme: "light",
    background: "default",
    viewport: standard,
    state: "dense",
    reviewFocus: ["agent list/detail panel hierarchy", "status chip language"],
    expectedEvidence: "screenshot",
  },
  {
    id: "agents-dark-default-wide-dense",
    path: "/agents",
    theme: "dark",
    background: "default",
    viewport: wide,
    state: "dense",
    reviewFocus: ["raised Agent workspace columns", "flat filter and entity rows"],
    expectedEvidence: "screenshot",
  },
  {
    id: "teams-light-default-compact-dense",
    path: "/teams",
    theme: "light",
    background: "default",
    viewport: compact,
    state: "dense",
    reviewFocus: ["Team canvas hierarchy", "content-sized canvas actions"],
    expectedEvidence: "screenshot",
  },
  {
    id: "teams-dark-default-standard-error",
    path: "/teams",
    theme: "dark",
    background: "default",
    viewport: standard,
    state: "error",
    reviewFocus: ["unavailable state contrast", "Team summary and recovery action"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-light-default-standard-dense",
    path: "/memory",
    theme: "light",
    background: "default",
    viewport: standard,
    state: "dense",
    reviewFocus: ["memory overview panel nesting", "metric/status chip consistency"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-dark-default-standard-dense",
    path: "/memory",
    theme: "dark",
    background: "default",
    viewport: standard,
    state: "dense",
    reviewFocus: ["overview metric strip", "review panel hierarchy"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-light-custom-compact-empty",
    path: "/memory",
    theme: "light",
    background: "custom",
    viewport: compact,
    state: "empty",
    reviewFocus: ["empty state readability", "narrow route header actions"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-graph-light-default-wide-dense",
    path: "/memory/graph",
    theme: "light",
    background: "default",
    viewport: wide,
    state: "dense",
    reviewFocus: ["graph page special-layout exception", "generic chrome consistency"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-manage-light-default-wide-dense",
    path: "/memory/manage",
    theme: "light",
    background: "default",
    viewport: wide,
    state: "dense",
    reviewFocus: ["management column hierarchy", "flat filters and stable actions"],
    expectedEvidence: "screenshot",
  },
  {
    id: "memory-graph-dark-default-wide-dense",
    path: "/memory/graph",
    theme: "dark",
    background: "default",
    viewport: wide,
    state: "dense",
    reviewFocus: ["graph metric strip", "filter canvas inspector hierarchy"],
    expectedEvidence: "screenshot",
  },
  {
    id: "config-light-default-standard-destructive",
    path: "/config",
    theme: "light",
    background: "default",
    viewport: standard,
    state: "destructive",
    reviewFocus: ["destructive action visibility", "quiet non-primary controls"],
    expectedEvidence: "screenshot",
  },
  {
    id: "config-dark-custom-wide-error",
    path: "/config",
    theme: "dark",
    background: "custom",
    viewport: wide,
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
    viewports: sortedUnique(
      scenarios.map((scenario) => classifyWorkbenchVisualViewport(scenario.viewport.width)),
    ),
    states: sortedUnique(scenarios.map((scenario) => scenario.state)),
    paths: sortedUnique(scenarios.map((scenario) => scenario.path)),
  };
}
