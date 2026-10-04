import type { ReactNode } from "react";
import { BookOpen, History, TrendingUp } from "lucide-react";
import { VButton, VSplitWorkspace, VSkeleton, VStateSurface } from "../../components/vui";
import styles from "../FinanceRoute.styles";
import "./FinanceResearch.layout.css";

export function FinanceResearchFrame({
  zh, sidebar, aside, children, actions, onHistory, onEvidence, loading = true,
}: {
  zh: boolean;
  sidebar?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  onHistory?: () => void;
  onEvidence?: () => void;
  loading?: boolean;
}) {
  return (
    <section className={styles.frame} aria-label={zh ? "炒股智能体" : "Investment assistant"} data-vui-domain-recipe="financial-assistant-workspace">
      <header className={styles.heading}>
        <div className={styles.brand}><span className={styles.brandIcon}><TrendingUp size={18} aria-hidden="true" /></span>{zh ? "炒股智能体" : "Investment assistant"}</div>
        <div className={styles.actions}>
          <span className={styles.market}>{zh ? "只读研究 · 行情未接入" : "Read-only research · quotes not connected"}</span>
          {onHistory ? <VButton variant="ghost" className={styles.mobileHistory} aria-label={zh ? "研究与记录" : "Research and history"} onPress={onHistory}><History size={16} /></VButton> : null}
          {onEvidence ? <VButton variant="ghost" className={styles.mobileEvidence} aria-label={zh ? "财报资料" : "Report library"} onPress={onEvidence}><BookOpen size={16} /></VButton> : null}
          {actions}
        </div>
      </header>
      <VSplitWorkspace
        resize={false}
        columnsClassName=""
        className={styles.split}
        sidebar={sidebar ?? <FramePlaceholder zh={zh} loading={loading} />}
        aside={aside ?? <FramePlaceholder zh={zh} loading={loading} evidence />}
        main={children}
      />
    </section>
  );
}

function FramePlaceholder({ zh, evidence = false, loading }: { zh: boolean; evidence?: boolean; loading: boolean }) {
  return <div className={evidence ? styles.aside : styles.rail}>
    <span className={styles.sectionHeading}>{evidence ? (zh ? "财报资料" : "Report library") : (zh ? "研究记录" : "Research history")}</span>
    {loading ? <div className={styles.skeleton} aria-hidden="true"><VSkeleton /><VSkeleton /><VSkeleton /></div> : null}
  </div>;
}

export function FinanceResearchLoading({ zh = true }: { zh?: boolean }) {
  return <FinanceResearchFrame zh={zh}>
    <div className={styles.state} role="status" aria-busy="true" data-vui-app="workbench" data-route-loading="finance" data-finance-entry-state="loading">
      <VStateSurface className={styles.stateSurface} title={zh ? "连接研究工作台" : "Opening research workspace"} tone="loading" busy />
    </div>
  </FinanceResearchFrame>;
}
