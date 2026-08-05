/**
 * Shared Teams workbench chrome: merged style map, layout panes, canvas tone helpers.
 * Extracted from useTeamsWorkbenchModel top-level constants (behavior-conserving).
 */
import { type PaneSpec } from "../../components/layout/paneLayoutPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import type { TeamCanvasNode } from "../../api/types";
import {
  nodeToneClass,
  roleBadgeToneClass,
} from "./teamCanvasNodePresentation";
import {
  workflowIngestionTone,
  workflowQualityTone,
  type WorkflowToneStyles,
} from "./workflowTone";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import shellStyles from "../TeamsRoute.styles";
import researchRouteStyles from "../TeamsRoute.research.styles";
import aiSearchRouteStyles from "../TeamsRoute.aiSearch.styles";
import experimentRouteStyles from "../TeamsRoute.experiment.styles";
import workflowRouteStyles from "../TeamsRoute.workflow.styles";

/** Wave 8F: thematic style clusters merged for call-site stability. */
export const teamsWorkbenchStyles = {
  ...shellStyles,
  ...researchRouteStyles,
  ...aiSearchRouteStyles,
  ...experimentRouteStyles,
  ...workflowRouteStyles,
} as Record<string, string>;

export const TEAMS_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.teams;

/** Left team list — VUI split sidebar with persisted width. */
export const TEAMS_RAIL_PANE: PaneSpec = {
  id: "rail",
  defaultWidth: 248,
  minWidth: 200,
  maxWidth: 360,
};

/** Right board inspector (workflow / stage tools) — persisted drag column. */
export const TEAMS_BOARD_INSPECTOR_PANE: PaneSpec = {
  id: "inspector",
  defaultWidth: 360,
  minWidth: 280,
  maxWidth: 560,
};

export type TeamsRouteProps = {
  forcedTeamId?: string;
  forcedResearchWorkspaceView?: ResearchWorkspaceView;
  sourceCollectionStandalone?: boolean;
};

const CANVAS_NODE_ROLE_BADGE_STYLES = {
  stale: teamsWorkbenchStyles.nodeRoleBadgeStale,
  open: teamsWorkbenchStyles.nodeRoleBadgeOpen,
  lead: teamsWorkbenchStyles.nodeRoleBadgeLead,
  advisor: teamsWorkbenchStyles.nodeRoleBadgeAdvisor,
  steward: teamsWorkbenchStyles.nodeRoleBadgeSteward,
  research: teamsWorkbenchStyles.nodeRoleBadgeResearch,
  self: teamsWorkbenchStyles.nodeRoleBadgeSelf,
  general: teamsWorkbenchStyles.nodeRoleBadgeGeneral,
};

const CANVAS_NODE_TONE_STYLES = {
  stale: teamsWorkbenchStyles.nodeStale,
  bound: teamsWorkbenchStyles.nodeBound,
  open: teamsWorkbenchStyles.nodeOpen,
};

export function roleBadgeTone(node: TeamCanvasNode, displayTone = "") {
  return roleBadgeToneClass(node, CANVAS_NODE_ROLE_BADGE_STYLES, displayTone);
}

export function nodeTone(node: TeamCanvasNode) {
  return nodeToneClass(node, CANVAS_NODE_TONE_STYLES);
}

export function workflowQualityToneBound(value: string) {
  return workflowQualityTone(value, teamsWorkbenchStyles as WorkflowToneStyles);
}

export function workflowIngestionToneBound(value: string) {
  return workflowIngestionTone(value, teamsWorkbenchStyles as WorkflowToneStyles);
}
