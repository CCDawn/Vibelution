import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTask,
} from "../../../api/types";
import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import { ChallengeCupIterationResultPackage } from "./ChallengeCupIterationResultPackage";
import { ResearchProjectAgentTaskPanel } from "./ResearchProjectAgentTaskPanel";
import css from "./ChallengeCupIterationStage.module.css";

type ChallengeProjection = NonNullable<ExperimentPlanningStatusPayload["challengeProgramProjection"]>;
type ChallengeCaseRecord = ChallengeProjection["stage3DeepResearchDelivery"]["caseRecords"][number];

type ChallengeCupIterationStageProps = {
  activeProjectId: string;
  cases: ChallengeCaseRecord[];
  isLoading: boolean;
  isStarting: boolean;
  onOpenTask?: (task: TeamResearchProjectAgentTask) => void;
  onStartTask: (
    taskKind: ResearchProjectAgentTaskKind,
    options?: { formalRetry?: boolean; retryTaskId?: string },
  ) => Promise<void>;
  startingTaskKind: ResearchProjectAgentTaskKind | null;
  taskError: string;
  tasks: TeamResearchProjectAgentTask[];
};

export function ChallengeCupIterationStage({
  activeProjectId,
  cases,
  isLoading,
  isStarting,
  onOpenTask,
  onStartTask,
  startingTaskKind,
  taskError,
  tasks,
}: ChallengeCupIterationStageProps) {
  return (
    <div className={css.stage}>
      <ChallengeCupIterationResultPackage cases={cases} />

      <ResearchProjectAgentTaskPanel
        activeProjectId={activeProjectId}
        errorMessage={taskError}
        isLoading={isLoading}
        isStarting={isStarting}
        onOpenTask={onOpenTask}
        onStartTask={onStartTask}
        stage="iteration"
        startingTaskKind={startingTaskKind}
        tasks={tasks}
      />
    </div>
  );
}
