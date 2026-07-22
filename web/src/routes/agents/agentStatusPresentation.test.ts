import { describe, expect, it } from "vitest";

import type { AgentConfigHealthIssue, AgentConfigWorkspaceAgent } from "../../api/types";

import {
  issueLabel,
  issueNextStep,
  issuePanelLabel,
  issueTone,
  modeLabel,
  runtimeNextStep,
  runtimeStatusLabel,
  runtimeStatusTone,
  workspaceHealthStatusLabel,
} from "./agentStatusPresentation";

function issue(severity: AgentConfigHealthIssue["severity"], code = "x"): AgentConfigHealthIssue {
  return {
    code,
    severity,
    title: `${severity}-title`,
    message: `${severity}-message`,
  } as AgentConfigHealthIssue;
}

describe("agentStatusPresentation", () => {
  it("ranks health tone by severity", () => {
    expect(issueTone([])).toBe("ok");
    expect(issueTone([issue("info")])).toBe("info");
    expect(issueTone([issue("warning"), issue("info")])).toBe("warning");
    expect(issueTone([issue("blocking"), issue("warning")])).toBe("blocking");
    expect(issueLabel([issue("blocking")], "zh")).toBe("阻塞");
    expect(issuePanelLabel([issue("info")], { statusReminders: "提醒", healthIssues: "问题" })).toBe("提醒");
    expect(issuePanelLabel([issue("warning")], { statusReminders: "提醒", healthIssues: "问题" })).toBe("问题");
  });

  it("labels workspace health and runtime states", () => {
    expect(workspaceHealthStatusLabel("blocked", "zh")).toBe("阻塞");
    expect(modeLabel("supervised_evolution", "en")).toBe("Supervised");

    const running = {
      status: "active",
      runtimeStatus: { state: "running", label: "Running" },
    } as AgentConfigWorkspaceAgent;
    expect(runtimeStatusTone(running)).toBe("running");
    expect(runtimeStatusLabel(running, "zh")).toBe("运行中");
    expect(runtimeNextStep(running, "zh")).toContain("会话");
  });

  it("guides next steps for inbox reminders", () => {
    const next = issueNextStep([issue("info", "pending_inbox_messages")], "zh");
    expect(next).toContain("Inbox");
  });
});
