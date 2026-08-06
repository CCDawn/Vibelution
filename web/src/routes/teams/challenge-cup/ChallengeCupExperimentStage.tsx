import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTask,
} from "../../../api/types";
import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import { ChallengeCupExperimentProtocol } from "./ChallengeCupExperimentProtocol";
import { ResearchProjectAgentTaskPanel } from "./ResearchProjectAgentTaskPanel";
import css from "./ChallengeCupExperimentStage.module.css";

type ChallengeProjection = NonNullable<ExperimentPlanningStatusPayload["challengeProgramProjection"]>;

type ChallengeCupExperimentStageProps = {
  activeProjectId: string;
  isLoading: boolean;
  isStarting: boolean;
  onOpenTask?: (task: TeamResearchProjectAgentTask) => void;
  onStartTask: (
    taskKind: ResearchProjectAgentTaskKind,
    options?: { formalRetry?: boolean; retryTaskId?: string },
  ) => Promise<void>;
  stage1: ChallengeProjection["stage1ComplianceReadiness"];
  stage2?: ChallengeProjection["stage2BatchGovernance"];
  startingTaskKind: ResearchProjectAgentTaskKind | null;
  taskError: string;
  tasks: TeamResearchProjectAgentTask[];
};

export function ChallengeCupExperimentStage({
  activeProjectId,
  isLoading,
  isStarting,
  onOpenTask,
  onStartTask,
  stage1,
  stage2,
  startingTaskKind,
  taskError,
  tasks,
}: ChallengeCupExperimentStageProps) {
  return (
    <div className={css.stage}>
      <ChallengeCupExperimentProtocol stage1={stage1} stage2={stage2} />

      <ResearchProjectAgentTaskPanel
        activeProjectId={activeProjectId}
        errorMessage={taskError}
        isLoading={isLoading}
        isStarting={isStarting}
        onOpenTask={onOpenTask}
        onStartTask={onStartTask}
        stage="experiment"
        startingTaskKind={startingTaskKind}
        tasks={tasks}
      />

    </div>
  );
}
