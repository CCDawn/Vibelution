/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// Keep the vui layout shell thin: this suite guards completion-flow slot wiring, not pane layout.
vi.mock("../../components/vui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/vui")>();
  return {
    ...actual,
    VCanvasWorkbenchPage: (props: {
      rail?: React.ReactNode;
      toolbar?: React.ReactNode;
      canvas: React.ReactNode;
      inspector?: React.ReactNode;
    }) => (
      <div data-testid="mock-canvas-workbench">
        <div data-testid="mock-canvas-rail">{props.rail}</div>
        <div data-testid="mock-canvas-toolbar">{props.toolbar}</div>
        <div data-testid="mock-canvas-body">{props.canvas}</div>
        <div data-testid="mock-canvas-inspector">{props.inspector}</div>
      </div>
    ),
  };
});

// Resolve the lazy completion-flow panel synchronously so its own visibility gate runs in-DOM.
vi.mock("./teamLazyPanels", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./teamLazyPanels")>();
  const panel = await import("../TeamKnowledgeCollectionCompletionFlowPanel");
  return { ...actual, TeamKnowledgeCollectionCompletionFlowPanel: panel.TeamKnowledgeCollectionCompletionFlowPanel };
});

import type { TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import styles from "../TeamsRoute.styles";
import { canvasViewStyle } from "./canvasGeometry";
import { renderTeamsWorkbenchCanvasPage, type TeamsWorkbenchCanvasPageProps } from "./renderTeamsWorkbenchCanvasPage";
import { createTeamsWorkspacePanelRenderers, type TeamsWorkspacePanelRenderContext } from "./teamsWorkspacePanelRenderers";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const FLOW_PANEL = 'section[aria-label="一键流程图"]';
const CANVAS_FRAME = '[data-testid="team-canvas-frame"]';

const nodes: TeamCanvasNode[] = [
  { id: "lead", type: "role", label: "Lead", role: "lead", purpose: "", agentId: "", agentCode: "", agentName: "", x: 100, y: 100, status: "ready" },
];
const frame = { width: 280, height: 240 };
const canvas: TeamOrganizationCanvas = {
  schemaVersion: 1, canvasKind: "team_organization_canvas", teamId: "team", updatedAt: "", path: "",
  viewport: { x: 0, y: 0, zoom: 1 }, nodes, edges: [],
};
const noop = () => undefined;

function pageProps(overrides: Partial<TeamsWorkbenchCanvasPageProps> = {}): TeamsWorkbenchCanvasPageProps {
  return {
    lang: "zh",
    styles,
    teamsRailResize: {
      sidebar: { id: "rail", defaultWidth: 280, minWidth: 240, maxWidth: 360 },
      aside: { id: "inspector", defaultWidth: 360, minWidth: 300, maxWidth: 520 },
    },
    selectedTeamContextTitle: "AI科研团队",
    teamShellRail: <aside data-testid="team-shell-rail" />,
    teamShellToolbar: <div data-testid="team-shell-toolbar" />,
    researchWorkflowTeamSelected: true,
    researchCanvasReadOnly: true,
    validationValid: true,
    hideCanvasToolbar: true,
    inspectorBody: null,
    selectedTeam: null,
    effectiveTeamId: "team",
    teamDetailLoadMode: "ready",
    canvas,
    displayCanvasNodes: nodes,
    visibleEdges: [],
    selectedNodeId: "lead",
    activeAgents: [],
    researchCanvasAutoLayoutActive: false,
    showCommunicationEdges: false,
    organizationEdgeCount: 0,
    communicationEdgeCount: 0,
    communicationEdgeHint: "",
    communicationEdgeButtonLabel: "",
    saveLabel: "",
    hasWritableCanvas: false,
    linkedChatRoomId: "",
    activeTeamMemberCount: 0,
    teamSyncPending: false,
    teamArchivePending: false,
    teamArchiveDisabledReason: "",
    showTeamLoadingSurface: false,
    teamWorkspaceLoadingTitle: "",
    teamWorkspaceLoadingMessage: "",
    teamDetailPending: false,
    teamCanvasPending: false,
    teamDetailError: false,
    teamCanvasError: false,
    canvasViewportStyle: canvasViewStyle(nodes, frame),
    canvasFrameSize: frame,
    canvasFrameRef: noop,
    nodeToneClass: () => "",
    roleBadgeToneClass: () => "",
    completionFlowSlot: null,
    onSelectNode: noop,
    onLayoutModeChange: noop,
    onToggleCommunicationEdges: noop,
    onAddNode: noop,
    onArchiveTeam: noop,
    onSyncRoom: noop,
    onNodePointerDown: noop,
    onNodePointerMove: noop,
    onNodePointerUp: noop,
    onNodePointerCancel: noop,
    ...overrides,
  };
}

/** Real route assembly: ctx -> panel renderer -> completionFlowSlot, exactly as useTeamsWorkbenchShellPhase wires it. */
function completionFlowSlotFor(ctx: TeamsWorkspacePanelRenderContext) {
  return createTeamsWorkspacePanelRenderers({
    lang: "zh",
    researchWorkflowTeamSelected: true,
    researchCanvasReadOnly: true,
    selectedTeamKnowledgeCollectionWorkRun: null,
    sourceCollectionCompletionFlow: { status: "queued", currentStageId: "finding" },
    sourceCollectionCompletionFlowNodes: [
      { stageId: "finding", status: "queued", label: "资料搜集", agentRole: "searcher", inputCount: 0, outputCount: 0 },
    ],
    sourceCollectionStageModules: [{ id: "finding", label: "资料搜集" }],
    workflowIngestionToneBound: () => "",
    sourceCollectionStagePrimaryAgentBinding: () => null,
    sourceCollectionStageReturnRoute: () => "/teams/team/stage/finding",
    openSourceCollectionStageAgentChat: noop,
    sourceCollectionStepClassName: () => "",
    runKnowledgeCollectionCompletionAction: noop,
    sourceCollectionCompletionActionDisabled: false,
    selectedTeamKnowledgeCollectionIngestPending: false,
    sourceCollectionActionDisabledTitle: () => undefined,
    sourceCollectionCompletionActionReadiness: null,
    ...ctx,
  }).renderKnowledgeCollectionCompletionFlowPanel();
}

let host: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
  }
  host?.remove();
  host = null;
  root = null;
});

function renderPage(overrides: Partial<TeamsWorkbenchCanvasPageProps> = {}) {
  act(() => {
    root?.render(<MemoryRouter>{renderTeamsWorkbenchCanvasPage(pageProps(overrides))}</MemoryRouter>);
  });
}

function mountPage(overrides: Partial<TeamsWorkbenchCanvasPageProps> = {}) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  renderPage(overrides);
  return host;
}

describe("renderTeamsWorkbenchCanvasPage completion-flow slot", () => {
  it("passes completionFlowSlot to the canvas surface regardless of researchCanvasReadOnly", () => {
    // Regression guard for f03478a8d: the page used to null the slot whenever the canvas was read-only,
    // which is the only state in which the panel itself agrees to render.
    const slot = <div data-testid="completion-flow-sentinel" />;
    const element = mountPage({ researchCanvasReadOnly: true, completionFlowSlot: slot });
    expect(element.querySelector('[data-testid="mock-canvas-body"] [data-testid="completion-flow-sentinel"]')).not.toBeNull();

    renderPage({ researchCanvasReadOnly: false, completionFlowSlot: slot });
    expect(element.querySelector('[data-testid="mock-canvas-body"] [data-testid="completion-flow-sentinel"]')).not.toBeNull();
  });

  it("shows the knowledge-collection completion panel for a research workflow team on the read-only canvas", () => {
    const element = mountPage({
      researchWorkflowTeamSelected: true,
      researchCanvasReadOnly: true,
      completionFlowSlot: completionFlowSlotFor({ researchWorkflowTeamSelected: true, researchCanvasReadOnly: true }),
    });

    const panel = element.querySelector<HTMLElement>(`[data-testid="mock-canvas-body"] ${FLOW_PANEL}`);
    expect(panel).not.toBeNull();
    expect(panel?.getAttribute("data-presentation")).toBe("board");
    expect(panel?.textContent).toContain("资料搜集");
    expect(element.querySelector(CANVAS_FRAME)).not.toBeNull();
  });

  it("keeps the panel hidden for an ordinary (non research-workflow) team through the panel's own gate", () => {
    const element = mountPage({
      researchWorkflowTeamSelected: false,
      researchCanvasReadOnly: true,
      completionFlowSlot: completionFlowSlotFor({ researchWorkflowTeamSelected: false, researchCanvasReadOnly: true }),
    });

    expect(element.querySelector(FLOW_PANEL)).toBeNull();
    expect(element.querySelector(CANVAS_FRAME)).not.toBeNull();
  });
});
