import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";

import { VButton, VContextualHint, VTooltip } from "../components/vui";
import type { SupervisedWorkflowStepId } from "./evolution/evolutionRouteModel";
import styles from "./EvolutionRoute.styles";

export type EvolutionSupervisedWorkflowStepView = {
  id: SupervisedWorkflowStepId;
  label: string;
  selected: boolean;
  current: boolean;
  meta: string;
  metric: string;
  preview: string;
  sessionRoute?: string;
  configRoute?: string;
  memberName?: string;
};

export type EvolutionSupervisedWorkflowMembersPanelProps = {
  lang: "zh" | "en";
  membersSource: "run" | "current_config";
  selectedStepLabel: string;
  membersHint?: string;
  showFollowLive: boolean;
  onFollowLive: () => void;
  stepCount: number;
  steps: EvolutionSupervisedWorkflowStepView[];
  onSelectStep: (stepId: SupervisedWorkflowStepId) => void;
};

/**
 * Supervised live workflow / members step rail.
 * Selection state and route building stay in EvolutionRoute.
 */
export function EvolutionSupervisedWorkflowMembersPanel({
  lang,
  membersSource,
  selectedStepLabel,
  membersHint,
  showFollowLive,
  onFollowLive,
  stepCount,
  steps,
  onSelectStep,
}: EvolutionSupervisedWorkflowMembersPanelProps) {
  return (
    <aside className={styles.supervisedWorkflowPanel} data-vui-region="evolution-supervised-workflow-members">
      <div className={styles.supervisedMembersHeader}>
        <div>
          <p className={styles.eyebrow}>
            {membersSource === "run" ? (lang === "zh" ? "运行步骤" : "Run steps") : (lang === "zh" ? "当前步骤" : "Current steps")}
          </p>
          <h3 className={`${styles.sectionTitle} ${styles.formLabelWithHint}`}>
            {selectedStepLabel}
            {membersHint ? (
              <VContextualHint
                content={membersHint}
                label={lang === "zh" ? "监督成员绑定说明" : "Supervised member binding help"}
                width="wide"
              />
            ) : null}
          </h3>
        </div>
        <div className={styles.supervisedMembersHeaderActions}>
          {showFollowLive ? (
            <VButton
              type="button"
              className={styles.supervisedWorkflowFollowButton}
              onClick={onFollowLive}
              tooltip={lang === "zh" ? "回到当前执行阶段" : "Follow the current run stage"}
            >
              {lang === "zh" ? "跟随现场" : "Follow live"}
            </VButton>
          ) : null}
          <span className={styles.secondaryPill}>{stepCount}</span>
        </div>
      </div>
      <div className={styles.workflowStepRail} aria-label={lang === "zh" ? "监督进化步骤导航" : "Supervised evolution step navigation"}>
        {steps.map((step) => {
          const sessionTooltip = step.memberName
            ? (lang === "zh" ? `打开监督成员 ${step.memberName} 的会话` : `Open supervised member session for ${step.memberName}`)
            : (lang === "zh" ? "打开监督会话" : "Open supervised session");
          const configTooltip = step.memberName
            ? (lang === "zh" ? `配置 ${step.memberName}` : `Configure ${step.memberName}`)
            : (lang === "zh" ? "配置" : "Config");
          return (
            <div
              key={step.id}
              className={step.current && !step.selected ? `${styles.workflowStepItem} ${styles.workflowStepItemCurrent}` : styles.workflowStepItem}
            >
              <VButton
                type="button"
                contentLayout="plain"
                className={step.selected ? `${styles.workflowStepButton} ${styles.workflowStepButtonActive}` : styles.workflowStepButton}
                aria-pressed={step.selected}
                onClick={() => onSelectStep(step.id)}
                tooltip={lang === "zh" ? `查看${step.label}` : `View ${step.label}`}
              >
                <span className={styles.workflowStepMeta}>
                  <span>{step.current ? (lang === "zh" ? "当前" : "Live") : step.metric}</span>
                  <span>{step.meta}</span>
                </span>
                <strong>{step.label}</strong>
                <span className={styles.workflowStepPreview}>{step.preview}</span>
              </VButton>
              {step.sessionRoute ? (
                <VTooltip content={sessionTooltip}>
                  <Link
                    className={styles.supervisedWorkflowSessionLink}
                    to={step.sessionRoute}
                    aria-label={sessionTooltip}
                  >
                    <span>{lang === "zh" ? "会话" : "Session"}</span>
                    <ArrowUpRight size={13} aria-hidden="true" />
                  </Link>
                </VTooltip>
              ) : step.configRoute ? (
                <VTooltip content={configTooltip}>
                  <Link className={styles.supervisedWorkflowSessionLink} to={step.configRoute}>
                    <span>{lang === "zh" ? "配置" : "Config"}</span>
                    <ArrowUpRight size={13} aria-hidden="true" />
                  </Link>
                </VTooltip>
              ) : null}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
