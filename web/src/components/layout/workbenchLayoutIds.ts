/**
 * Stable workbench layoutIds under vibelution.pane-layouts.v1 (Wave 4C).
 * Routes/recipes must use these constants — do not invent ad-hoc width keys.
 */

export const WORKBENCH_LAYOUT_IDS = {
  agents: "agents",
  chat: "chat",
  configSettings: "config-settings",
  configModelAssets: "config-model-assets",
  evolution: "evolution",
  evolutionSelf: "evolution-self",
  git: "git",
  kernelTaskCenter: "kernel-task-center",
  launcher: "launcher",
  logs: "logs",
  memory: "memory",
  promptTemplates: "prompt-templates",
  skills: "skills",
  supervisedReview: "supervised-review",
  teams: "teams",
  tools: "tools",
} as const;

export type WorkbenchLayoutId = (typeof WORKBENCH_LAYOUT_IDS)[keyof typeof WORKBENCH_LAYOUT_IDS];

export const WORKBENCH_LAYOUT_ID_LIST: readonly WorkbenchLayoutId[] = Object.values(WORKBENCH_LAYOUT_IDS);

export function isWorkbenchLayoutId(value: string): value is WorkbenchLayoutId {
  return (WORKBENCH_LAYOUT_ID_LIST as readonly string[]).includes(value);
}
