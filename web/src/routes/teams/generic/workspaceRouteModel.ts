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
  for (const key of ["researchView", "workflowId", "workflowRunId", "workflowWorkspace", "teamView", "teamConversation", "teamConversationTeamId", "teamMember", "companion", "questionId", "runId", "challengeQuestion", "challengeRun", "room", "session", "agent"]) next.delete(key);
  next.set("team", teamId);
  next.delete("teamId");
  next.set("teamWorkspace", "flows");
  return next;
}

export function workflowTeamDiscussionParams(params: URLSearchParams, teamId: string, roomId?: string): URLSearchParams {
  const next = workflowTeamParams(params, teamId);
  next.delete("teamWorkspace");
  next.set("teamConversationTeamId", teamId);
  next.set("teamConversation", "group");
  next.set("teamView", "discussion");
  if (roomId) next.set("room", roomId);
  return next;
}
