import { Bot, Settings2 } from "lucide-react";

import type { ResearchStageAgentBinding } from "../../TeamResearchStageAgentPanel";
import { agentDisplayInfo } from "../../agentDisplay";
import {
  VRouteLinkButton,
  VStatusChip,
  VTooltip,
  type VStatusTone,
} from "../../../components/vui";
import {
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentManagementRoute,
  researchStageAgentModelLabel,
} from "../researchStageAgentPresentation";
import type { ResearchStageType } from "../source-collection/stageProjection";
import css from "./ChallengeCupStageAgentConfigurationPanel.module.css";
import taskCardStyles from "./ResearchProjectAgentTaskPanel.styles";

type ChallengeCupStageAgentConfigurationPanelProps = {
  bindings: ResearchStageAgentBinding[];
  lang: "zh" | "en";
  stageType: ResearchStageType;
};

function configurationTone(binding: ResearchStageAgentBinding): VStatusTone {
  if (!binding.agent) {
    return binding.agentId ? "warning" : "neutral";
  }
  const tone = researchStageAgentConfigTone(binding.agent);
  if (tone === "ready") return "accent";
  if (tone === "blocked" || tone === "warning") return "warning";
  return "neutral";
}

function configurationLabel(binding: ResearchStageAgentBinding, lang: "zh" | "en") {
  if (!binding.agent) {
    return binding.agentId ? (lang === "zh" ? "需修复" : "needs repair") : (lang === "zh" ? "待绑定" : "not bound");
  }
  return researchStageAgentConfigStatusLabel(binding.agent, lang);
}

export function ChallengeCupStageAgentConfigurationPanel({
  bindings,
  lang,
  stageType,
}: ChallengeCupStageAgentConfigurationPanelProps) {
  return (
    <section
      className={css.panel}
      aria-label={lang === "zh" ? "Agent 配置" : "Agent configuration"}
      data-testid="challenge-cup-stage-agent-configuration"
    >
      <header className={css.header}>
        <h3>{lang === "zh" ? "Agent 配置" : "Agent configuration"}</h3>
      </header>
      <div className={css.cards}>
        {bindings.map((binding) => {
          const agentName = binding.agent
            ? agentDisplayInfo(binding.agent, lang, {
              name: binding.bindingLabel || (lang === "zh" ? binding.zh : binding.en),
            }).name
            : binding.agentId || (lang === "zh" ? "未绑定" : "Not bound");
          const detail = `${lang === "zh" ? binding.zhFocus : binding.enFocus} · ${researchStageAgentModelLabel(binding.agent, lang)}`;
          const hasAgent = Boolean(binding.agent);

          return (
            <article className={`${taskCardStyles.card} ${css.card}`} key={`${stageType}-${binding.key}`}>
              <span className={`${taskCardStyles.role} ${css.identity}`}>
                <Bot size={15} aria-hidden="true" />
                <span>{agentName}</span>
              </span>
              <div className={`${taskCardStyles.controls} ${css.controls}`}>
                <VTooltip content={detail}>
                  <span>
                    <VStatusChip tone={configurationTone(binding)}>
                      {configurationLabel(binding, lang)}
                    </VStatusChip>
                  </span>
                </VTooltip>
                <VRouteLinkButton
                  density="compact"
                  icon={<Settings2 size={14} />}
                  to={binding.agentId ? researchStageAgentManagementRoute(binding.agentId) : "/agents"}
                  variant="secondary"
                >
                  {hasAgent ? (lang === "zh" ? "配置" : "Configure") : (lang === "zh" ? "绑定" : "Bind")}
                </VRouteLinkButton>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
