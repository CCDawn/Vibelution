import { useCallback, useMemo } from "react";

import type { SessionToolApprovalDecision } from "../../api/chat";
import type {
  AgentToolGovernanceRequest,
  SessionDetail,
  SessionToolApprovalRequest,
} from "../../api/types";
import {
  toolApprovalLabels,
  toolApprovalRiskLabel,
  toolApprovalScopeLabel,
} from "./toolApprovalLabels";
import {
  APPROVAL_DEV_TOOL_BUNDLE_TOOLS,
  approvalGrantMapsToSessionTool,
  toolApprovalActionPreview,
  toolApprovalDisplayName,
} from "./toolApprovalPreview";
import type { ChatSessionWorkspaceToolApproval } from "./ChatSessionWorkspacePanel";

export interface UseChatToolApprovalBridgeParams {
  detail: SessionDetail | null | undefined;
  sessionToolApprovals: SessionToolApprovalRequest[] | undefined;
  activeSessionId: string | null;
  lang: "zh" | "en";
  resolveSessionToolApprovalMutation: {
    isPending: boolean;
    variables?: { request: SessionToolApprovalRequest; decision: SessionToolApprovalDecision };
    mutate: (variables: { request: SessionToolApprovalRequest; decision: SessionToolApprovalDecision }) => void;
  };
  resolveToolApprovalMutation: {
    isPending: boolean;
    variables?: { request: AgentToolGovernanceRequest; decision: "approve" | "reject" };
    mutate: (variables: { request: AgentToolGovernanceRequest; decision: "approve" | "reject" }) => void;
  };
  /** b3: one-click session trust for the execute/write development tools. */
  trustDevelopmentToolsMutation: {
    isPending: boolean;
    variables?: { sessionId: string; requestId: string };
    mutate: (variables: { sessionId: string; requestId: string }) => void;
  };
}

export interface ChatToolApprovalBridgeState {
  pendingToolGovernanceApproval: AgentToolGovernanceRequest | null;
  pendingSessionToolApproval: SessionToolApprovalRequest | null;
  sessionIdsNeedingApproval: string[];
  pendingToolApprovalLabels: Array<{ id: string; label: string }>;
  pendingToolApprovalRawTitle: string;
  pendingToolApprovalActionPreview: string;
  pendingToolApprovalScope: string;
  pendingToolApprovalRisk: string;
  pendingToolApprovalPending: boolean;
  toolApproval: ChatSessionWorkspaceToolApproval | null;
}

export function useChatToolApprovalBridge({
  detail,
  sessionToolApprovals,
  activeSessionId,
  lang,
  resolveSessionToolApprovalMutation,
  resolveToolApprovalMutation,
  trustDevelopmentToolsMutation,
}: UseChatToolApprovalBridgeParams): ChatToolApprovalBridgeState {
  const pendingToolGovernanceApproval = useMemo(
    () => (detail?.pendingToolGovernanceRequests ?? []).find((request) => request.status === "pending_review") ?? null,
    [detail?.pendingToolGovernanceRequests],
  );

  const pendingSessionToolApproval = useMemo(
    () => (sessionToolApprovals ?? []).find((request) => request.status === "pending") ?? null,
    [sessionToolApprovals],
  );

  const sessionIdsNeedingApproval = useMemo(
    () => (
      activeSessionId
      && (pendingSessionToolApproval || pendingToolGovernanceApproval)
        ? [activeSessionId]
        : []
    ),
    [activeSessionId, pendingSessionToolApproval, pendingToolGovernanceApproval],
  );

  const pendingToolApprovalLabels = useMemo(
    () => pendingSessionToolApproval
      ? [{
        id: pendingSessionToolApproval.toolName,
        label: toolApprovalDisplayName(pendingSessionToolApproval.toolName, lang),
      }]
      : toolApprovalLabels(pendingToolGovernanceApproval),
    [lang, pendingSessionToolApproval, pendingToolGovernanceApproval],
  );

  const pendingToolApprovalRawTitle = pendingToolApprovalLabels.map((item) => item.id).join("、");

  const pendingToolApprovalActionPreview = pendingSessionToolApproval
    ? toolApprovalActionPreview(pendingSessionToolApproval.argumentSummary, pendingSessionToolApproval.toolName, lang)
    : pendingToolApprovalLabels.map((item) => item.label).join(" · ");

  const pendingToolApprovalScope = pendingSessionToolApproval
    ? (lang === "zh" ? "本次调用" : "this call")
    : toolApprovalScopeLabel(pendingToolGovernanceApproval?.grantScope, lang);

  const pendingToolApprovalRisk = toolApprovalRiskLabel(
    pendingSessionToolApproval?.risk ?? pendingToolGovernanceApproval?.riskLevel,
    lang,
  );

  const pendingToolApprovalPending = Boolean(
    pendingSessionToolApproval
      ? (
        resolveSessionToolApprovalMutation.isPending
        && resolveSessionToolApprovalMutation.variables?.request.requestId === pendingSessionToolApproval.requestId
      )
      : (
        pendingToolGovernanceApproval
        && resolveToolApprovalMutation.isPending
        && resolveToolApprovalMutation.variables?.request.requestId === pendingToolGovernanceApproval.requestId
      ),
  );

  const handleApproveToolApproval = useCallback(() => {
    if (pendingSessionToolApproval) {
      resolveSessionToolApprovalMutation.mutate({
        request: pendingSessionToolApproval,
        decision: "accept",
      });
      return;
    }
    if (!pendingToolGovernanceApproval) {
      return;
    }
    resolveToolApprovalMutation.mutate({ request: pendingToolGovernanceApproval, decision: "approve" });
  }, [pendingSessionToolApproval, pendingToolGovernanceApproval, resolveSessionToolApprovalMutation, resolveToolApprovalMutation]);

  /** A2b: the "A" button copy says session-scoped — make the decision match. */
  const handleApproveToolForSession = useMemo(() => {
    if (
      !pendingSessionToolApproval
      || pendingSessionToolApproval.approval === "always"
    ) {
      return undefined;
    }
    const availableDecisions = pendingSessionToolApproval.availableDecisions;
    if (approvalGrantMapsToSessionTool(pendingSessionToolApproval.toolName)) {
      // Shell/file dev tools: exact-args and durable grants never repeat-hit,
      // so "A" maps to the tool-level session grant the copy describes.
      if (availableDecisions.includes("acceptForSessionTool")) {
        return () => {
          resolveSessionToolApprovalMutation.mutate({
            request: pendingSessionToolApproval,
            decision: "acceptForSessionTool",
          });
        };
      }
      // Red-lined calls (network/destructive risk) keep the narrow same-scope tier.
      if (!availableDecisions.includes("acceptForSession")) {
        return undefined;
      }
      return () => {
        resolveSessionToolApprovalMutation.mutate({
          request: pendingSessionToolApproval,
          decision: "acceptForSession",
        });
      };
    }
    if (
      !(
        availableDecisions.includes("acceptAlways")
        || availableDecisions.includes("acceptForSession")
      )
    ) {
      return undefined;
    }
    return () => {
      const decision = availableDecisions.includes("acceptAlways")
        ? "acceptAlways"
        : "acceptForSession";
      resolveSessionToolApprovalMutation.mutate({
        request: pendingSessionToolApproval,
        decision,
      });
    };
  }, [pendingSessionToolApproval, resolveSessionToolApprovalMutation]);

  /**
   * b1: coarser opt-in tier — every call of this tool for the rest of the
   * session. For shell/file dev tools the "A" button already performs exactly
   * this action, so the redundant standalone button is not offered again.
   */
  const handleApproveToolForSessionTool = useMemo(() => {
    if (
      !pendingSessionToolApproval
      || approvalGrantMapsToSessionTool(pendingSessionToolApproval.toolName)
      || !pendingSessionToolApproval.availableDecisions.includes("acceptForSessionTool")
    ) {
      return undefined;
    }
    return () => {
      resolveSessionToolApprovalMutation.mutate({
        request: pendingSessionToolApproval,
        decision: "acceptForSessionTool",
      });
    };
  }, [pendingSessionToolApproval, resolveSessionToolApprovalMutation]);

  /**
   * b3: one click trusts every execute/write development tool for this
   * session. The server resolves the current pending request exactly like
   * acceptForSessionTool and adds the same tool-level grants for the rest of
   * the bundle; no new grant mechanism, expiry, or red line is introduced.
   */
  const handleApproveDevelopmentBundle = useMemo(() => {
    if (
      !pendingSessionToolApproval
      || pendingSessionToolApproval.approval === "always"
      || !APPROVAL_DEV_TOOL_BUNDLE_TOOLS.has(pendingSessionToolApproval.toolName)
      || !pendingSessionToolApproval.availableDecisions.includes("acceptForSessionTool")
    ) {
      return undefined;
    }
    return () => {
      trustDevelopmentToolsMutation.mutate({
        sessionId: pendingSessionToolApproval.sessionId,
        requestId: pendingSessionToolApproval.requestId,
      });
    };
  }, [pendingSessionToolApproval, trustDevelopmentToolsMutation]);

  /** b3: time-boxed delegation for low-risk assistant manage actions. */
  const handleApproveWithActionWindow = useMemo(() => {
    if (
      !pendingSessionToolApproval
      || !pendingSessionToolApproval.availableDecisions.includes("acceptWithActionWindow")
      || pendingSessionToolApproval.assistantActionWindow?.eligible !== true
    ) {
      return undefined;
    }
    return () => {
      resolveSessionToolApprovalMutation.mutate({
        request: pendingSessionToolApproval,
        decision: "acceptWithActionWindow",
      });
    };
  }, [pendingSessionToolApproval, resolveSessionToolApprovalMutation]);

  const handleRejectToolApproval = useCallback(() => {
    if (pendingSessionToolApproval) {
      resolveSessionToolApprovalMutation.mutate({
        request: pendingSessionToolApproval,
        decision: "decline",
      });
      return;
    }
    if (!pendingToolGovernanceApproval) {
      return;
    }
    resolveToolApprovalMutation.mutate({ request: pendingToolGovernanceApproval, decision: "reject" });
  }, [pendingSessionToolApproval, pendingToolGovernanceApproval, resolveSessionToolApprovalMutation, resolveToolApprovalMutation]);

  const toolApproval = useMemo(() => {
    if (!pendingSessionToolApproval && !pendingToolGovernanceApproval) {
      return null;
    }
    return {
      requestId: pendingSessionToolApproval?.requestId
        || pendingToolGovernanceApproval?.requestId
        || "",
      pending: pendingToolApprovalPending,
      rawTitle: pendingToolApprovalRawTitle,
      riskLabel: pendingToolApprovalRisk,
      scopeLabel: pendingToolApprovalScope,
      toolLabels: pendingToolApprovalLabels,
      actionPreview: pendingToolApprovalActionPreview,
      sessionGrantScope: pendingSessionToolApproval?.sessionGrantScope,
      toolName: pendingSessionToolApproval?.toolName || pendingToolApprovalLabels[0]?.id,
      assistantActionWindow: pendingSessionToolApproval?.assistantActionWindow,
      onApprove: handleApproveToolApproval,
      onApproveForSession: handleApproveToolForSession,
      onApproveForSessionTool: handleApproveToolForSessionTool,
      onApproveWithActionWindow: handleApproveWithActionWindow,
      onApproveForDevelopmentBundle: handleApproveDevelopmentBundle,
      onReject: handleRejectToolApproval,
    };
  }, [
    handleApproveDevelopmentBundle,
    handleApproveToolApproval,
    handleApproveToolForSession,
    handleApproveToolForSessionTool,
    handleApproveWithActionWindow,
    handleRejectToolApproval,
    pendingSessionToolApproval,
    pendingToolGovernanceApproval,
    pendingToolApprovalPending,
    pendingToolApprovalRawTitle,
    pendingToolApprovalRisk,
    pendingToolApprovalScope,
    pendingToolApprovalLabels,
    pendingToolApprovalActionPreview,
  ]);

  return {
    pendingToolGovernanceApproval,
    pendingSessionToolApproval,
    sessionIdsNeedingApproval,
    pendingToolApprovalLabels,
    pendingToolApprovalRawTitle,
    pendingToolApprovalActionPreview,
    pendingToolApprovalScope,
    pendingToolApprovalRisk,
    pendingToolApprovalPending,
    toolApproval,
  };
}
