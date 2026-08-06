import { Link } from "react-router-dom";

import { VTooltip } from "../../../components/vui";
import {
  TeamStageCard,
  TeamStagePipeline,
} from "../../../components/vui/product/team-management";
import {
  CHALLENGE_CUP_STAGES,
  CHALLENGE_CUP_STAGE_META,
  challengeCupStageTone,
  type ChallengeCupStage,
  type ChallengeCupStageStatus,
} from "./challengeCupStageModel";
import css from "./ChallengeCupStageRail.module.css";

export type ChallengeCupStageObject = {
  id: string;
  title: string;
  detail: string;
  tone: "neutral" | "active" | "ready" | "warning";
  href: string;
};

type ChallengeCupStageRailProps = {
  activeStage: ChallengeCupStage;
  stageState: (stage: ChallengeCupStage) => ChallengeCupStageStatus;
  stageObjects: ChallengeCupStageObject[];
  onSelectStage: (stage: ChallengeCupStage) => void;
};

export function ChallengeCupStageRail({
  activeStage,
  stageState,
  stageObjects,
  onSelectStage,
}: ChallengeCupStageRailProps) {
  return (
    <nav className={css.rail} aria-label="科研阶段">
      <TeamStagePipeline ariaLabel="科研阶段">
        {CHALLENGE_CUP_STAGES.map((stage, index) => {
          const meta = CHALLENGE_CUP_STAGE_META[stage];
          const state = stageState(stage);
          return (
            <TeamStageCard
              key={stage}
              index={index}
              label={meta.label}
              metric=""
              nextLabel={meta.detail}
              onActivate={() => onSelectStage(stage)}
              selected={activeStage === stage}
              status={state.label}
              title={meta.detail}
              tone={challengeCupStageTone(state.tone)}
            />
          );
        })}
      </TeamStagePipeline>

      {stageObjects.length > 0 ? <section className={css.objects} aria-label="当前阶段对象">
        {stageObjects.map((item, index) => (
          <VTooltip content={item.detail} key={item.id} width="wide">
            <Link
              className={css.objectLink}
              data-selected={index === 0 ? "true" : undefined}
              to={item.href}
            >
              <i aria-hidden="true" className={css.dot} data-tone={item.tone} />
              <span className={css.objectTitle}>{item.title}</span>
            </Link>
          </VTooltip>
        ))}
      </section> : null}
    </nav>
  );
}
