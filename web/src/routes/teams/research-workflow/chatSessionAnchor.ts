/**
 * Task 7: exact Agent session anchors for workflow nodes.
 * Never fall back to agent default DM when task/turn missing — report degraded.
 */

export type ChatSessionAnchor = {
  sessionId: string;
  focusTask: string;
  focusTurn: string;
  returnTo: string;
  returnLabel: string;
};

export type ChatSessionAnchorParseResult =
  | { ok: true; anchor: ChatSessionAnchor }
  | { ok: false; degraded: true; reason: string; sessionId: string };

export function buildChatSessionDeepLink(anchor: ChatSessionAnchor): string {
  const params = new URLSearchParams();
  params.set("session", anchor.sessionId);
  params.set("focusTask", anchor.focusTask);
  params.set("focusTurn", anchor.focusTurn);
  if (anchor.returnTo) params.set("returnTo", anchor.returnTo);
  if (anchor.returnLabel) params.set("returnLabel", anchor.returnLabel);
  return `/chat?${params.toString()}`;
}

export function parseChatSessionAnchor(search: string): ChatSessionAnchorParseResult {
  const raw = search.startsWith("?") ? search.slice(1) : search;
  const params = new URLSearchParams(raw);
  const sessionId = (params.get("session") || "").trim();
  const focusTask = (params.get("focusTask") || "").trim();
  const focusTurn = (params.get("focusTurn") || "").trim();
  const returnTo = (params.get("returnTo") || "").trim();
  const returnLabel = (params.get("returnLabel") || "").trim();

  if (!sessionId) {
    return { ok: false, degraded: true, reason: "missing_session", sessionId: "" };
  }
  if (!focusTask || !focusTurn) {
    return {
      ok: false,
      degraded: true,
      reason: !focusTask ? "missing_focus_task" : "missing_focus_turn",
      sessionId,
    };
  }
  return {
    ok: true,
    anchor: { sessionId, focusTask, focusTurn, returnTo, returnLabel },
  };
}

export function buildWorkflowReturnTo(options: {
  teamId: string;
  runId: string;
  nodeId: string;
}): string {
  const params = new URLSearchParams();
  if (!options.teamId.trim()) throw new Error("teamId 不能为空");
  params.set("teamId", options.teamId.trim());
  params.set("researchView", "workflow");
  params.set("runId", options.runId);
  params.set("node", options.nodeId);
  return `/teams?${params.toString()}`;
}
