/**
 * Single compatibility resolver: legacy research query/path → canonical workflow URL.
 * Do not scatter legacy researchView branches in business components.
 */

import {
  CHALLENGE_CUP_NODE_IDS,
  CHALLENGE_CUP_WORKFLOW_ID,
  type ChallengeCupNodeId,
} from "../../../api/types/researchWorkflow";

export type CanonicalWorkflowLocation = {
  pathname: string;
  searchParams: URLSearchParams;
  /** True when input was already canonical. */
  wasCanonical: boolean;
  /** Source key for telemetry. */
  mappedFrom: string;
};

export type LegacyResolveInput = {
  pathname: string;
  search: string;
  teamId?: string;
};

const COLLECTION_STAGE_TO_NODE: Record<string, ChallengeCupNodeId> = {
  search: "source_finding",
  collection: "source_finding",
  finding: "source_finding",
  review: "source_extraction",
  candidate: "source_extraction",
  screening: "source_extraction",
  extraction: "source_extraction",
  graph: "evidence_relations",
  relations: "evidence_relations",
  ingest: "knowledge_ingestion",
  memory: "knowledge_ingestion",
  ingestion: "knowledge_ingestion",
};

const RESEARCH_VIEW_TO_NODE: Record<string, ChallengeCupNodeId | undefined> = {
  knowledge_collection: "source_finding",
  source_collection: "source_finding",
  experiment: "hypothesis_design",
  iteration: "controlled_run",
  ingestion: "knowledge_ingestion",
  graph: "evidence_relations",
  candidates: "source_extraction",
};

function isChallengeCupNodeId(value: string): value is ChallengeCupNodeId {
  return (CHALLENGE_CUP_NODE_IDS as readonly string[]).includes(value);
}

export function buildCanonicalWorkflowSearch(options: {
  teamId?: string;
  runId?: string;
  node?: string;
  panel?: string;
  workflowId?: string;
}): string {
  const params = new URLSearchParams();
  if (options.teamId) params.set("team", options.teamId);
  params.set("researchView", "workflow");
  params.set("workflowId", options.workflowId || CHALLENGE_CUP_WORKFLOW_ID);
  if (options.runId) params.set("runId", options.runId);
  if (options.node && isChallengeCupNodeId(options.node)) params.set("node", options.node);
  if (options.panel) params.set("panel", options.panel);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function resolveLegacyResearchLocation(input: LegacyResolveInput): CanonicalWorkflowLocation {
  const pathname = input.pathname || "/teams";
  const incoming = new URLSearchParams(input.search.startsWith("?") ? input.search.slice(1) : input.search);
  const teamId = (input.teamId || incoming.get("team") || "").trim();

  // /research/flow-canvas → workflow + agents panel
  if (pathname.includes("/research/flow-canvas")) {
    return {
      pathname: "/teams",
      searchParams: new URLSearchParams(
        buildCanonicalWorkflowSearch({ teamId, panel: "agents" }).replace(/^\?/, ""),
      ),
      wasCanonical: false,
      mappedFrom: "path:/research/flow-canvas",
    };
  }

  // /research → teams workflow
  if (pathname === "/research" || pathname.endsWith("/research")) {
    return {
      pathname: "/teams",
      searchParams: new URLSearchParams(buildCanonicalWorkflowSearch({ teamId }).replace(/^\?/, "")),
      wasCanonical: false,
      mappedFrom: "path:/research",
    };
  }

  const researchView = (incoming.get("researchView") || "").trim();
  const collectionStage = (incoming.get("collectionStage") || "").trim();
  const teamMode = (incoming.get("teamMode") || "").trim();
  const existingNode = (incoming.get("node") || "").trim();
  const runId = (incoming.get("runId") || "").trim();
  const panel = (incoming.get("panel") || "").trim();

  if (researchView === "workflow") {
    const params = new URLSearchParams(buildCanonicalWorkflowSearch({
      teamId,
      runId,
      node: existingNode,
      panel: panel || undefined,
      workflowId: incoming.get("workflowId") || undefined,
    }).replace(/^\?/, ""));
    return {
      pathname: "/teams",
      searchParams: params,
      wasCanonical: true,
      mappedFrom: "researchView:workflow",
    };
  }

  let mappedFrom = "default";
  let node: string | undefined;
  let mappedPanel: string | undefined = panel || undefined;

  if (researchView === "overview" || researchView === "") {
    mappedFrom = researchView === "overview" ? "researchView:overview" : "default";
  } else if (researchView === "canvas" || teamMode === "canvas") {
    mappedFrom = researchView === "canvas" ? "researchView:canvas" : "teamMode:canvas";
    mappedPanel = "agents";
  } else if (researchView === "coordination" || researchView === "discussion") {
    mappedFrom = `researchView:${researchView}`;
    mappedPanel = "team";
  } else if (RESEARCH_VIEW_TO_NODE[researchView]) {
    node = RESEARCH_VIEW_TO_NODE[researchView];
    mappedFrom = `researchView:${researchView}`;
  } else if (researchView) {
    mappedFrom = `researchView:unknown:${researchView}`;
  }

  if (collectionStage) {
    const mapped = COLLECTION_STAGE_TO_NODE[collectionStage];
    if (mapped) {
      node = mapped;
      mappedFrom = `collectionStage:${collectionStage}`;
    } else {
      mappedFrom = `collectionStage:unknown:${collectionStage}`;
    }
  }

  if (existingNode && isChallengeCupNodeId(existingNode)) {
    node = existingNode;
  }

  return {
    pathname: "/teams",
    searchParams: new URLSearchParams(
      buildCanonicalWorkflowSearch({
        teamId,
        runId,
        node,
        panel: mappedPanel,
      }).replace(/^\?/, ""),
    ),
    wasCanonical: false,
    mappedFrom,
  };
}

export function canonicalHref(location: CanonicalWorkflowLocation): string {
  const qs = location.searchParams.toString();
  return qs ? `${location.pathname}?${qs}` : location.pathname;
}
