/** @vitest-environment happy-dom */

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type {
  ResearchWorkflowNodeDetail,
  ScopedSessionAnchor,
} from "../../../api/types/research-workflow/core";
import { NodeSessionSection } from "./NodeSessionSection";

function anchor(overrides: Partial<ScopedSessionAnchor> = {}): ScopedSessionAnchor {
  return {
    scopeKind: "workflow_candidate",
    selectionId: "selection-1",
    candidateId: "H1",
    sessionId: "child-H1",
    sessionAttempt: 1,
    taskId: "task-H1",
    status: "running",
    chatDeepLink: "/chat?session=child-H1&focusTask=task-H1",
    fragmentRef: null,
    sessionAnchorDegraded: false,
    ...overrides,
  };
}

function detail(overrides: Partial<ResearchWorkflowNodeDetail> = {}): ResearchWorkflowNodeDetail {
  return {
    runId: "run-1",
    teamId: "team-1",
    nodeId: "hypothesis_design",
    runVersion: 1,
    actorKind: "agent",
    primaryRoleKey: "hypothesis_designer",
    label: "假说设计",
    runtimeCurrent: true,
    status: "running",
    attempts: [],
    commandOffers: [],
    latestEventSequence: 1,
    generatedAt: "2026-08-22T00:00:00Z",
    sessionId: "root-session-1",
    taskId: "task-root",
    turnId: "turn-root",
    sessionAttempt: 1,
    chatDeepLink: "/chat?session=root-session-1&focusTask=task-root&focusTurn=turn-root",
    sessionAnchorDegraded: false,
    scopedSessions: [],
    ...overrides,
  };
}

function renderSection(input: ResearchWorkflowNodeDetail) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <NodeSessionSection detail={input} />
    </MemoryRouter>,
  );
}

describe("NodeSessionSection", () => {
  it("shows the node root separately and preserves backend/selection candidate order", () => {
    const markup = renderSection(detail({
      sessionId: "child-compat-anchor",
      rootSession: {
        scopeKind: "workflow_node_root",
        sessionId: "root-session-1",
        status: "running",
        sessionAttempt: 1,
        chatDeepLink: "/chat?session=root-session-1",
        sessionAnchorDegraded: false,
      },
      scopedSessions: [
        anchor({ candidateId: "H2", sessionId: "child-H2", taskId: "task-H2", chatDeepLink: "/chat?session=child-H2&focusTask=task-H2" }),
        anchor({ candidateId: "H1", sessionId: "child-H1", taskId: "task-H1", status: "succeeded", fragmentRef: "fragment-H1" }),
      ],
    }));

    expect(markup).toContain("节点根会话");
    expect(markup).toContain("root-session-1");
    expect(markup).not.toContain("child-compat-anchor");
    expect(markup).toContain("查看节点总览");
    expect(markup.indexOf("候选 H2")).toBeLessThan(markup.indexOf("候选 H1"));
    expect(markup).toContain("child-H2");
    expect(markup).toContain("running");
    expect(markup).toContain("succeeded");
    expect(markup).toContain("fragment-H1");
    expect(markup).toContain('href="/chat?session=child-H2');
  });

  it("renders a clear empty state when neither root nor child sessions exist", () => {
    const markup = renderSection(detail({
      sessionId: null,
      taskId: null,
      turnId: null,
      chatDeepLink: null,
      scopedSessions: [],
    }));

    expect(markup).toContain("未绑定节点根会话");
    expect(markup).not.toContain("打开精确会话");
  });

  it("keeps completed child sessions visible and degrades without a link", () => {
    const markup = renderSection(detail({
      scopedSessions: [
        anchor({
          candidateId: "H3",
          sessionId: "child-H3",
          taskId: "task-H3",
          status: "succeeded",
          chatDeepLink: null,
        }),
      ],
    }));

    expect(markup).toContain("候选 H3");
    expect(markup).toContain("succeeded");
    expect(markup).toContain("会话链接暂不可用");
    expect(markup).not.toContain('href="null"');
    expect(markup).not.toContain('href="/chat?session=child-H3');
  });

  it("fails closed when trust metadata is missing from root and child links", () => {
    const markup = renderSection(detail({
      sessionAnchorDegraded: undefined,
      scopedSessions: [anchor({ sessionAnchorDegraded: undefined })],
      rootSession: {
        scopeKind: "workflow_node_root",
        sessionId: "root-session-1",
        status: "running",
        sessionAttempt: 1,
        chatDeepLink: "/chat?session=root-session-1",
      },
    }));

    expect(markup.match(/会话链接暂不可用/g)).toHaveLength(2);
    expect(markup).not.toContain('href="/chat?session=root-session-1');
    expect(markup).not.toContain('href="/chat?session=child-H1');
  });

  it("does not promote a legacy child scalar to the node root", () => {
    const markup = renderSection(detail({
      rootSession: null,
      sessionId: "child-H2",
      chatDeepLink: "/chat?session=child-H2",
      scopedSessions: [
        anchor({ candidateId: "H1" }),
        anchor({ candidateId: "H2", sessionId: "child-H2", chatDeepLink: "/chat?session=child-H2", sessionAnchorDegraded: false }),
      ],
    }));

    expect(markup).toContain("未绑定节点根会话");
    expect(markup).not.toContain("查看节点总览");
  });

  it("keeps a failed placeholder visible without a link and explains scoped retry", () => {
    const markup = renderSection(detail({
      scopedSessions: [
        anchor({
          candidateId: "H2",
          sessionId: null,
          taskId: null,
          status: "failed",
          chatDeepLink: null,
          sessionAnchorDegraded: true,
        }),
      ],
    }));

    expect(markup).toContain("候选 H2");
    expect(markup).toContain("failed");
    expect(markup).toContain("节点重试仅处理失败候选 H2");
    expect(markup).toContain("会话链接暂不可用");
    expect(markup).not.toContain("href=");
  });

  it("falls back to chatRoute only when it is a non-empty trusted anchor", () => {
    const markup = renderSection(detail({
      rootSession: {
        scopeKind: "workflow_node_root",
        sessionId: "root-route-session",
        status: "running",
        chatDeepLink: "   ",
        chatRoute: "/chat?session=root-route-session",
        sessionAnchorDegraded: false,
      },
      scopedSessions: [anchor({
        candidateId: "H2",
        chatDeepLink: "   ",
        chatRoute: "/chat?session=child-route-session",
      })],
    }));

    expect(markup).toContain('href="/chat?session=root-route-session"');
    expect(markup).toContain('href="/chat?session=child-route-session"');
  });

  it.each(["blocked", "cancelled", "timed_out", "timeout"]) (
    "labels %s child sessions as failure context",
    (status) => {
      const markup = renderSection(detail({
        scopedSessions: [anchor({ status })],
      }));

      expect(markup).toContain("查看失败上下文");
    },
  );
});
