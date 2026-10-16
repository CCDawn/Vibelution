import type { TeamsRouteProps } from "../teamsWorkbenchChrome";

/** Explicit conversations, native artifacts and retained research tools keep their routes. */
export function shouldOfferGenericWorkspace(props: TeamsRouteProps, params: URLSearchParams): boolean {
  const view = props.forcedResearchWorkspaceView || params.get("researchView") || "";
  if (props.sourceCollectionStandalone || params.get("workflowWorkspace") === "legacy") return false;
  if (view && view !== "overview" && view !== "workflow") return false;
  return !["teamView", "teamConversation", "room", "session", "questionId", "runId", "challengeQuestion", "challengeRun", "workflowRunId"].some(key => params.has(key));
}

export function workflowTeamParams(params: URLSearchParams, teamId: string): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of ["researchView", "workflowId", "workflowRunId", "workflowWorkspace", "teamView", "teamConversation", "questionId", "runId", "challengeQuestion", "challengeRun", "room", "session", "agent"]) next.delete(key);
  next.set("team", teamId);
  next.delete("teamId");
  next.set("teamWorkspace", "flows");
  return next;
}
