import { Bot, Link2 } from "lucide-react";
import { Link } from "react-router-dom";

import type { AgentConfigWorkspaceAgent } from "../api/types";
import { agentDisplayInfo } from "./agentDisplay";
import type { ResearchStageAgentRoleDefinition } from "./teams/researchStageRoles";
import type { ResearchStageType } from "./teams/source-collection/stageProjection";
import {
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentManagementRoute,
  researchStageAgentModelLabel,
} from "./teams/researchStageAgentPresentation";
import researchStyles from "./TeamsRoute.research.styles";

const styles = researchStyles as Record<string, string>;

type Lang = "zh" | "en";

export type ResearchStageAgentBinding = ResearchStageAgentRoleDefinition & {
  agentId: string;
  agent: AgentConfigWorkspaceAgent | null;
  bindingLabel: string;
  bindingSource: string;
};

export type TeamResearchStageAgentSummaryProps = {
  lang: Lang;
  bindings: ResearchStageAgentBinding[];
  agentDirectoryHydrating: boolean;
};

export type TeamResearchStageAgentPanelProps = {
  lang: Lang;
  stageType: ResearchStageType;
  bindings: ResearchStageAgentBinding[];
  variant?: "compact" | "page";
};

/** Compact ready/blocked/missing strip for a research stage. */
export function TeamResearchStageAgentSummary({
  lang,
  bindings,
  agentDirectoryHydrating,
}: TeamResearchStageAgentSummaryProps) {
  const readyCount = bindings.filter((binding) => binding.agent && researchStageAgentConfigTone(binding.agent) === "ready").length;
  const blockedCount = bindings.filter((binding) => binding.agentId && !binding.agent).length
    + bindings.filter((binding) => binding.agent && researchStageAgentConfigTone(binding.agent) === "blocked").length;
  const missingCount = bindings.filter((binding) => !binding.agentId).length;
  const toneStyle = agentDirectoryHydrating
    ? styles.researchStageAgentSummaryLoading
    : blockedCount > 0
      ? styles.researchStageAgentSummaryBlocked
      : missingCount > 0
        ? styles.researchStageAgentSummaryMissing
        : styles.researchStageAgentSummaryReady;

  return (
    <div className={`${styles.researchStageAgentSummary} ${toneStyle}`}>
      <Bot size={13} />
      <span>{agentDirectoryHydrating
        ? (lang === "zh" ? "正在读取成员配置" : "Loading member setup")
        : (lang === "zh" ? "阶段成员" : "Stage members")}
      </span>
      <strong>{agentDirectoryHydrating ? "…" : `${readyCount}/${bindings.length}`}</strong>
    </div>
  );
}

/** Stage agent configuration grid for research stages. */
export function TeamResearchStageAgentPanel({
  lang,
  stageType,
  bindings,
  variant = "page",
}: TeamResearchStageAgentPanelProps) {
  const readyCount = bindings.filter((binding) => binding.agent && researchStageAgentConfigTone(binding.agent) === "ready").length;
  const panelClassName = [
    styles.researchStageAgentPanel,
    variant === "compact" ? styles.researchStageAgentPanelCompact : "",
  ].filter(Boolean).join(" ");

  return (
    <section className={panelClassName} aria-label={lang === "zh" ? "阶段 Agent 配置" : "Stage Agent configuration"}>
      <div className={styles.researchStageAgentPanelHeader}>
        <div>
          <strong>{lang === "zh" ? "本阶段 Agent" : "Stage Agents"}</strong>
          <span>{readyCount}/{bindings.length} {lang === "zh" ? "可用" : "ready"}</span>
        </div>
        <Link to="/agents">
          <Link2 size={13} />
          {lang === "zh" ? "Agent 管理" : "Agent management"}
        </Link>
      </div>
      <div className={styles.researchStageAgentGrid}>
        {bindings.map((binding) => {
          const tone = binding.agent
            ? researchStageAgentConfigTone(binding.agent)
            : binding.agentId
              ? "blocked"
              : "missing";
          const info = agentDisplayInfo(binding.agent, lang, {
            name: binding.bindingLabel || (lang === "zh" ? binding.zh : binding.en),
          });
          const agentName = binding.agent
            ? info.name
            : binding.agentId
              ? binding.agentId
              : (lang === "zh" ? "未绑定" : "Not bound");
          const statusLabel = binding.agent
            ? researchStageAgentConfigStatusLabel(binding.agent, lang)
            : binding.agentId
              ? (lang === "zh" ? "引用失效" : "missing reference")
              : (lang === "zh" ? "待绑定" : "missing");

          return (
            <article
              key={`${stageType}-${binding.key}`}
              className={[
                styles.researchStageAgentCard,
                styles[`researchStageAgentCard_${tone}`] ?? "",
              ].filter(Boolean).join(" ")}
            >
              <div className={styles.researchStageAgentRole}>
                <small>{lang === "zh" ? binding.zh : binding.en}</small>
                <strong>{agentName}</strong>
              </div>
              <div className={styles.researchStageAgentMeta}>
                <span>{lang === "zh" ? binding.zhFocus : binding.enFocus}</span>
                <span>{researchStageAgentModelLabel(binding.agent, lang)}</span>
              </div>
              <div className={styles.researchStageAgentActions}>
                <span>{statusLabel}</span>
                <Link to={binding.agentId ? researchStageAgentManagementRoute(binding.agentId) : "/agents"}>
                  <Link2 size={12} />
                  {binding.agent ? (lang === "zh" ? "配置" : "Configure") : (lang === "zh" ? "绑定" : "Bind")}
                </Link>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
