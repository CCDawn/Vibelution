import { Link2, Search } from "lucide-react";

import { VNativeButton } from "../components/vui";
import styles from "./TeamsRoute.styles";

type TeamSourceCollectionSourceDetailLang = "zh" | "en";

export type TeamSourceCollectionSourceDetailLink = {
  id: string;
  href: string;
  label: string;
  title: string;
};

export type TeamSourceCollectionSourceDetailAction = {
  id: string;
  target: string;
  runId: string;
  label: string;
  title?: string;
};

export type TeamSourceCollectionSourceDetailEvidence = {
  id: string;
  label: string;
  value: string;
  title: string;
  href?: string;
};

export type TeamSourceCollectionSourceDetailFact = {
  label: string;
  value: string;
};

type TeamSourceCollectionSourceDetailPanelProps = {
  lang: TeamSourceCollectionSourceDetailLang;
  title: string;
  candidateId: string;
  statusLabel: string;
  statusToneClassName: string;
  readableLinks: TeamSourceCollectionSourceDetailLink[];
  actions: TeamSourceCollectionSourceDetailAction[];
  noticeMessage: string;
  searchEvidence: TeamSourceCollectionSourceDetailEvidence[];
  facts: TeamSourceCollectionSourceDetailFact[];
  pending: boolean;
  onOpenTarget: (target: string, runId?: string) => void;
};

export function TeamSourceCollectionSourceDetailPanel({
  lang,
  title,
  candidateId,
  statusLabel,
  statusToneClassName,
  readableLinks,
  actions,
  noticeMessage,
  searchEvidence,
  facts,
  pending,
  onOpenTarget,
}: TeamSourceCollectionSourceDetailPanelProps) {
  const isZh = lang === "zh";

  return (
    <section className={styles.sourceCollectionSourceDetailPanel} aria-label={isZh ? "资料来源详情" : "Source provenance detail"}>
      <div className={styles.sourceCollectionSourceDetailHeader}>
        <div>
          <strong title={title}>{title}</strong>
          <span>{candidateId}</span>
        </div>
        <span className={`${styles.workflowTag} ${statusToneClassName}`}>{statusLabel}</span>
      </div>
      <div className={styles.sourceCollectionSourceDetailActions}>
        {readableLinks.map((link) => (
          <a key={link.id} href={link.href} target="_blank" rel="noreferrer" title={link.title}>
            <Link2 size={12} />
            {link.label}
          </a>
        ))}
        {actions.map((action) => (
          <VNativeButton
            key={action.id}
            type="button"
            onClick={() => onOpenTarget(action.target, action.runId || undefined)}
            disabled={pending}
            title={action.title}
          >
            <Link2 size={12} />
            {action.label}
          </VNativeButton>
        ))}
        {noticeMessage ? (
          <span className={styles.sourceCollectionSourceDetailNotice}>{noticeMessage}</span>
        ) : null}
      </div>
      {searchEvidence.length ? (
        <details className={styles.sourceCollectionSearchEvidence}>
          <summary>
            <Search size={12} />
            {isZh ? "查看搜索证据" : "View search evidence"}
          </summary>
          <div className={styles.sourceCollectionSearchEvidenceBody}>
            {searchEvidence.map((item) => (
              <span key={item.id}>
                <b>{item.label}</b>
                {item.href ? (
                  <a href={item.href} target="_blank" rel="noreferrer" title={item.title}>
                    <Link2 size={12} />
                    {item.value}
                  </a>
                ) : (
                  <code title={item.title}>{item.value}</code>
                )}
              </span>
            ))}
          </div>
        </details>
      ) : null}
      <div className={styles.sourceCollectionSourceDetailFacts}>
        {facts.map((fact) => (
          <span key={`${fact.label}-${fact.value}`}>
            <b>{fact.label}</b>
            <code title={fact.value}>{fact.value}</code>
          </span>
        ))}
      </div>
    </section>
  );
}
