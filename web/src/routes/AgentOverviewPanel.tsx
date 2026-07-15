import { type ReactNode } from "react";

import {
  Bot,
  Brain,
  CheckCircle2,
  Database,
  FolderTree,
  Layers3,
  MessageSquare,
  ShieldCheck,
  UserRound,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import styles from "./AgentOverviewPanel.styles";

export type AgentOverviewIcon =
  | "model"
  | "llm"
  | "system"
  | "prompt"
  | "tools"
  | "memory"
  | "persona"
  | "task"
  | "territory"
  | "context"
  | "runtime"
  | "communication"
  | "delegation";

export type AgentOverviewFact = {
  id: string;
  icon: AgentOverviewIcon;
  title: string;
  label: string;
  value: string;
};

export type AgentOverviewTerritory = {
  eyebrow: string;
  title: string;
  privateLabel: string;
  privateValue: string;
  sharedLabel: string;
  sharedValue: string;
  writeBoundaryLabel: string;
  writeBoundaryValue: string;
};

export type AgentOverviewModeMembership = {
  eyebrow: string;
  title: string;
  modes: Array<{
    id: string;
    label: string;
  }>;
};

export type AgentOverviewPanelPolicy = {
  id: string;
  icon: AgentOverviewIcon;
  label: string;
  value: string;
};

export type AgentOverviewPanelProps = {
  facts: AgentOverviewFact[];
  territory: AgentOverviewTerritory;
  modeMembership: AgentOverviewModeMembership;
  policies: AgentOverviewPanelPolicy[];
  children?: ReactNode;
};

const overviewIcons: Record<AgentOverviewIcon, LucideIcon> = {
  model: Bot,
  llm: Brain,
  system: Layers3,
  prompt: Brain,
  tools: Wrench,
  memory: Database,
  persona: UserRound,
  task: CheckCircle2,
  territory: FolderTree,
  context: MessageSquare,
  runtime: ShieldCheck,
  communication: Users,
  delegation: Layers3,
};

function AgentOverviewIconView({ icon }: { icon: AgentOverviewIcon }) {
  const Icon = overviewIcons[icon];
  return <Icon size={16} />;
}

const TECHNICAL_FACT_IDS = new Set(["system-ids", "tools", "memory", "territory"]);

function FactGrid({ facts }: { facts: AgentOverviewFact[] }) {
  return (
    <div className={styles.factGrid}>
      {facts.map((fact) => (
        <section key={fact.id} title={fact.title}>
          <AgentOverviewIconView icon={fact.icon} />
          <span>{fact.label}</span>
          <strong>{fact.value}</strong>
        </section>
      ))}
    </div>
  );
}

export function AgentOverviewPanel({ facts, territory, modeMembership, policies, children }: AgentOverviewPanelProps) {
  const primaryFacts = facts.filter((fact) => !TECHNICAL_FACT_IDS.has(fact.id));
  const technicalFacts = facts.filter((fact) => TECHNICAL_FACT_IDS.has(fact.id));

  return (
    <>
      <FactGrid facts={primaryFacts} />

      <section className={styles.detailSection}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{modeMembership.eyebrow}</p>
            <h3>{modeMembership.title}</h3>
          </div>
          <Layers3 size={16} />
        </div>
        <div className={styles.pillList}>
          {modeMembership.modes.map((mode) => (
            <span key={mode.id}>{mode.label}</span>
          ))}
        </div>
      </section>

      {children}

      <section className={styles.policyGrid}>
        {policies.map((policy) => (
          <div key={policy.id}>
            <AgentOverviewIconView icon={policy.icon} />
            <strong>{policy.label}</strong>
            <span>{policy.value}</span>
          </div>
        ))}
      </section>

      <details className={styles.technicalDetails}>
        <summary>
          <FolderTree size={15} />
          <span>技术信息</span>
          <small>工作空间、策略与系统标识</small>
        </summary>
        <div className={styles.technicalContent}>
          <FactGrid facts={technicalFacts} />
          <section className={styles.detailSection}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{territory.eyebrow}</p>
                <h3>{territory.title}</h3>
              </div>
              <FolderTree size={16} />
            </div>
            <div className={styles.boundarySummaryGrid}>
              <span>
                <strong>{territory.privateLabel}</strong>
                <small>{territory.privateValue}</small>
              </span>
              <span>
                <strong>{territory.sharedLabel}</strong>
                <small>{territory.sharedValue}</small>
              </span>
              <span>
                <strong>{territory.writeBoundaryLabel}</strong>
                <small>{territory.writeBoundaryValue}</small>
              </span>
            </div>
          </section>
        </div>
      </details>
    </>
  );
}
