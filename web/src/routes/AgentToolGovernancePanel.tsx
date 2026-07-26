import { ShieldCheck, Wrench } from "lucide-react";

import { AgentToolGovernanceRequest } from "../api/types";
import { VButton, VContextualHint } from "../components/vui";
import { governanceStatusLabel } from "./agents/agentStatusPresentation";
import styles from "./AgentToolGovernancePanel.styles";

export type AgentToolGovernancePanelCopy = {
  toolGovernanceTitle: string;
  toolGovernancePending: string;
  toolGovernanceReject: string;
  toolGovernanceApprove: string;
  toolGovernanceEmpty: string;
};

type AgentToolGovernancePanelProps = {
  copy: AgentToolGovernancePanelCopy;
  lang: "zh" | "en";
  requests: AgentToolGovernanceRequest[];
  pendingRequestId: string | null;
  onResolve: (request: AgentToolGovernanceRequest, decision: "approve" | "reject") => void;
  onConfigure: () => void;
};

export { governanceStatusLabel };

function governanceRiskLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
  };
  const en: Record<string, string> = {
    low: "Low risk",
    medium: "Medium risk",
    high: "High risk",
  };
  return ((lang === "zh" ? zh : en)[normalized] ?? normalized) || "-";
}

function governanceDeltaSummary(request: AgentToolGovernanceRequest | undefined, lang: "zh" | "en") {
  const delta = request?.policyDelta;
  if (!delta) {
    return "-";
  }
  const parts = [
    `${lang === "zh" ? "授权" : "Grant"} ${delta.grantTools?.length ?? 0}`,
    `${lang === "zh" ? "撤销" : "Revoke"} ${delta.revokeTools?.length ?? 0}`,
    `${lang === "zh" ? "禁用" : "Block"} ${delta.blockTools?.length ?? 0}`,
    `${lang === "zh" ? "解除禁用" : "Unblock"} ${delta.unblockTools?.length ?? 0}`,
  ];
  return parts.join(" · ");
}

export function AgentToolGovernancePanel({
  copy,
  lang,
  requests,
  pendingRequestId,
  onResolve,
  onConfigure,
}: AgentToolGovernancePanelProps) {
  const pendingCount = requests.filter((item) => item.status === "pending_review").length;
  const governanceHint = lang === "zh"
    ? "工具治理变更从工具页发起；这里保留最近记录和待审批处理。"
    : "Tool governance changes start from the Tools page. Recent records and approvals remain visible here.";

  return (
    <section className={styles.configEditor}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.toolGovernanceTitle}</p>
          <div className={styles.titleRow}>
            <h3>{copy.toolGovernancePending}: {pendingCount}</h3>
            <VContextualHint
              label={lang === "zh" ? "工具治理说明" : "Tool governance details"}
              content={governanceHint}
              width="wide"
            />
          </div>
        </div>
        <ShieldCheck size={16} />
      </div>
      <div className={styles.toolGovernanceList}>
        {requests.length ? (
          requests.map((request) => {
            const requestPending = pendingRequestId === request.requestId;
            return (
              <article key={request.requestId} className={styles.toolGovernanceItem}>
                <div>
                  <strong>{governanceStatusLabel(request.status, lang)} · {governanceRiskLabel(request.riskLevel, lang)}</strong>
                  <span>{governanceDeltaSummary(request, lang)}</span>
                  <small>{request.reason || request.approvalReason || request.requestId}</small>
                </div>
                {request.status === "pending_review" ? (
                  <div className={styles.governanceActions}>
                    <VButton
                      type="button"
                      variant="secondary"
                      isDisabled={requestPending}
                      onPress={() => onResolve(request, "reject")}
                    >
                      {copy.toolGovernanceReject}
                    </VButton>
                    <VButton
                      type="button"
                      variant="primary"
                      isDisabled={requestPending}
                      onPress={() => onResolve(request, "approve")}
                    >
                      {copy.toolGovernanceApprove}
                    </VButton>
                  </div>
                ) : null}
              </article>
            );
          })
        ) : (
          <p className={styles.emptyText}>{copy.toolGovernanceEmpty}</p>
        )}
      </div>
      <div className={styles.editorActions}>
        <VButton
          type="button"
          variant="primary"
          icon={<Wrench size={15} />}
          onPress={onConfigure}
        >
          {lang === "zh" ? "去工具页配置" : "Configure in tools"}
        </VButton>
      </div>
    </section>
  );
}
