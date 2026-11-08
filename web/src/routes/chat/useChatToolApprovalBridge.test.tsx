// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useChatToolApprovalBridge,
  type UseChatToolApprovalBridgeParams,
} from "./useChatToolApprovalBridge";
import type { SessionToolApprovalRequest } from "../../api/types";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(async () => {
  if (root && container) {
    await act(async () => root!.unmount());
  }
  container?.remove();
  container = null;
  root = null;
});

function approvalRequest(overrides: Partial<SessionToolApprovalRequest>): SessionToolApprovalRequest {
  return {
    requestId: "req-1",
    sessionId: "session-a",
    turnId: "turn-a",
    agentId: "agent-a",
    callId: "call-1",
    toolName: "exec_command",
    approval: "on_request",
    risk: "execute",
    argumentsHash: "hash",
    argumentSummary: {},
    sessionGrantScope: { kind: "shell_command_family", family: "pytest" },
    decisionFingerprint: "decision-a",
    configRevision: 3,
    configHash: "config-hash-a",
    permissionPreset: "request_approval",
    availableDecisions: ["accept", "acceptForSession", "acceptForSessionTool", "acceptAlways", "decline", "cancel"],
    createdAt: "2026-01-01T00:00:00Z",
    status: "pending",
    decision: null,
    resolvedAt: null,
    ...overrides,
  };
}

type RecordedMutations = {
  sessionDecisions: Array<{ requestId: string; decision: string }>;
  trustCalls: Array<{ sessionId: string; requestId: string }>;
};

function mountBridge(request: SessionToolApprovalRequest | null) {
  const recorded: RecordedMutations = { sessionDecisions: [], trustCalls: [] };
  const params: UseChatToolApprovalBridgeParams = {
    detail: null,
    sessionToolApprovals: request ? [request] : undefined,
    activeSessionId: "session-a",
    lang: "zh",
    resolveSessionToolApprovalMutation: {
      isPending: false,
      mutate: (variables) => {
        recorded.sessionDecisions.push({
          requestId: variables.request.requestId,
          decision: variables.decision,
        });
      },
    },
    resolveToolApprovalMutation: {
      isPending: false,
      mutate: () => undefined,
    },
    trustDevelopmentToolsMutation: {
      isPending: false,
      mutate: (variables) => {
        recorded.trustCalls.push(variables);
      },
    },
  };
  let bridge: ReturnType<typeof useChatToolApprovalBridge> | null = null;
  function Harness() {
    bridge = useChatToolApprovalBridge(params);
    return null;
  }
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container!);
  act(() => {
    root!.render(<Harness />);
  });
  return { bridge: bridge!, recorded };
}

describe("useChatToolApprovalBridge always-tier mapping (A2b/b3)", () => {
  it("maps the A button to acceptForSessionTool for shell tools and drops the duplicate button", () => {
    const request = approvalRequest({ toolName: "exec_command" });
    const { bridge, recorded } = mountBridge(request);
    expect(bridge.toolApproval?.onApproveForSession).toBeTypeOf("function");
    act(() => bridge.toolApproval!.onApproveForSession!());
    expect(recorded.sessionDecisions).toEqual([
      { requestId: "req-1", decision: "acceptForSessionTool" },
    ]);
    // The A button already performs the tool-session action; no duplicate.
    expect(bridge.toolApproval?.onApproveForSessionTool).toBeUndefined();
    // b3: the one-click bundle is offered and posts the pending identity.
    act(() => bridge.toolApproval!.onApproveForDevelopmentBundle!());
    expect(recorded.trustCalls).toEqual([{ sessionId: "session-a", requestId: "req-1" }]);
  });

  it("keeps the durable acceptAlways decision for web_fetch", () => {
    const request = approvalRequest({
      toolName: "web_fetch_tool",
      risk: "network",
      sessionGrantScope: { kind: "exact_arguments", argumentsHash: "hash" },
      availableDecisions: ["accept", "acceptForSession", "acceptAlways", "decline", "cancel"],
    });
    const { bridge, recorded } = mountBridge(request);
    act(() => bridge.toolApproval!.onApproveForSession!());
    expect(recorded.sessionDecisions).toEqual([
      { requestId: "req-1", decision: "acceptAlways" },
    ]);
    // Network risk: neither the tool-level grant nor the dev bundle.
    expect(bridge.toolApproval?.onApproveForSessionTool).toBeUndefined();
    expect(bridge.toolApproval?.onApproveForDevelopmentBundle).toBeUndefined();
  });

  it("falls back to the same-scope session tier when the tool-level grant is red-lined", () => {
    const request = approvalRequest({
      toolName: "exec_command",
      risk: "network",
      availableDecisions: ["accept", "acceptForSession", "acceptAlways", "decline", "cancel"],
    });
    const { bridge, recorded } = mountBridge(request);
    act(() => bridge.toolApproval!.onApproveForSession!());
    expect(recorded.sessionDecisions).toEqual([
      { requestId: "req-1", decision: "acceptForSession" },
    ]);
    expect(bridge.toolApproval?.onApproveForDevelopmentBundle).toBeUndefined();
  });

  it("offers no always-tier or bundle for always-pinned requests", () => {
    const request = approvalRequest({
      toolName: "personal_assistant_computer_action_tool",
      approval: "always",
      risk: "destructive",
      availableDecisions: ["accept", "decline", "cancel"],
    });
    const { bridge, recorded } = mountBridge(request);
    expect(bridge.toolApproval?.onApproveForSession).toBeUndefined();
    expect(bridge.toolApproval?.onApproveForSessionTool).toBeUndefined();
    expect(bridge.toolApproval?.onApproveForDevelopmentBundle).toBeUndefined();
    expect(recorded.sessionDecisions).toEqual([]);
  });
});
