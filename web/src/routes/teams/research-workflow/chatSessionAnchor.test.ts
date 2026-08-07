import { describe, expect, it } from "vitest";

import {
  buildChatSessionDeepLink,
  buildWorkflowReturnTo,
  parseChatSessionAnchor,
} from "./chatSessionAnchor";

describe("chatSessionAnchor", () => {
  it("builds deep link with focusTask focusTurn and returnTo", () => {
    const href = buildChatSessionDeepLink({
      sessionId: "sess-1",
      focusTask: "task-9",
      focusTurn: "turn-3",
      returnTo: "/teams?researchView=workflow&runId=run-1&node=source_finding",
      returnLabel: "workflow",
    });
    expect(href).toContain("/chat?");
    expect(href).toContain("session=sess-1");
    expect(href).toContain("focusTask=task-9");
    expect(href).toContain("focusTurn=turn-3");
    expect(href).toContain("returnTo=");
  });

  it("parses complete anchor", () => {
    const result = parseChatSessionAnchor(
      "?session=s1&focusTask=t1&focusTurn=u1&returnTo=%2Fteams&returnLabel=wf",
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.anchor.focusTask).toBe("t1");
      expect(result.anchor.focusTurn).toBe("u1");
    }
  });

  it("degrades without falling back to agent default when task/turn missing", () => {
    const missingTask = parseChatSessionAnchor("?session=s1&focusTurn=u1");
    expect(missingTask.ok).toBe(false);
    if (!missingTask.ok) {
      expect(missingTask.degraded).toBe(true);
      expect(missingTask.sessionId).toBe("s1");
      expect(missingTask.reason).toBe("missing_focus_task");
    }
  });

  it("builds workflow return path preserving run and node", () => {
    const path = buildWorkflowReturnTo({ teamId: "research-team", runId: "run-9", nodeId: "smoke_gate" });
    expect(path).toContain("researchView=workflow");
    expect(path).toContain("runId=run-9");
    expect(path).toContain("node=smoke_gate");
  });
});
