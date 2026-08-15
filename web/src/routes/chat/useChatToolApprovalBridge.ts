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
  toolApprovalActionPreview,
  toolApprovalDisplayName,
} from "./toolApprovalPreview";

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
  toolApproval: {
    requestId?: string;
    pending: boolean;
    rawTitle: string;
    riskLabel: string;
    scopeLabel: string;
    toolLabels: Array<{ id: string; label: string }>;
    actionPreview?: string;
    sessionGrantScope?: Record<string, unknown>;
    toolName?: string;
  } | null;
  handleApproveToolApproval: () => void;
  handleApproveToolForSession: (() => void) | undefined;
  handleRejectToolApproval: () => void;
}

export function useChatToolApprovalBridge({
  detail,
  sessionToolApprovals,
  activeSessionId,
  lang,
  resolveSessionToolApprovalMutation,
  resolveToolApprovalMutation,
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
    ? toolApprovalActionPreview(pendingSessionToolApproval.argumentSummary, pendingSessionToolApproval.toolName)
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

  const handleApproveToolForSession = useMemo(() => {
    if (
      !pendingSessionToolApproval
      || pendingSessionToolApproval.approval === "always"
      || !(
        pendingSessionToolApproval.availableDecisions.includes("acceptAlways")
        || pendingSessionToolApproval.availableDecisions.includes("acceptForSession")
      )
    ) {
      return undefined;
    }
    return () => {
      const decision = pendingSessionToolApproval.availableDecisions.includes("acceptAlways")
        ? "acceptAlways"
        : "acceptForSession";
      resolveSessionToolApprovalMutation.mutate({
        request: pendingSessionToolApproval,
        decision,
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
    };
  }, [
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
    handleApproveToolApproval,
    handleApproveToolForSession,
    handleRejectToolApproval,
  };
}
