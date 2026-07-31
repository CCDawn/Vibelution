import { LoaderCircle } from "lucide-react";
import { Suspense, lazy } from "react";

import type {
  SelfEvolutionOverview,
  SelfEvolutionAutonomousLoopRun,
  SelfEvolutionTransaction,
  SelfObservationRun,
  SelfObservationRunStartRequest,
  SupervisedWorktreeRun,
} from "../api/types";
import type { Language } from "../i18n/dictionary";
import styles from "./EvolutionSelfTrackBoundary.styles";

const LazySelfEvolutionTrack = lazy(() =>
  import("./SelfEvolutionTrack").then((module) => ({ default: module.SelfEvolutionTrack })),
);

export type EvolutionSelfTrackBoundaryProps = {
  lang: Language;
  overview?: SelfEvolutionOverview;
  worktreeRun?: SupervisedWorktreeRun | null;
  observationRun?: SelfObservationRun | null;
  autonomousRun?: SelfEvolutionAutonomousLoopRun | null;
  goalInput: string;
  onGoalInputChange: (value: string) => void;
  onStartRun: () => void;
  onAutonomousAction: (
    runId: string,
    action: "approve" | "reject" | "retry_cleanup",
    comment?: string,
  ) => void;
  onStartObservation: (payload: SelfObservationRunStartRequest) => void;
  onTerminateObservation: (runId: string) => void;
  onWorktreeAction: (runId: string, action: string) => void;
  onDeleteHistoryGroups: (txnIds: string[]) => void;
  startPending: boolean;
  observationStartPending: boolean;
  observationActionPending: boolean;
  worktreeActionPending: boolean;
  autonomousActionPending: boolean;
  deleteHistoryPending: boolean;
  startWorktreeError: string;
  observationStartError: string;
  observationActionError: string;
  worktreeActionError: string;
  autonomousActionError: string;
  deleteHistoryError: string;
  actionFeedback: string;
  runLocked: boolean;
  worktreeRunLocked: boolean;
  transactions: SelfEvolutionTransaction[];
  loading: boolean;
};

function selfTrackFallback(lang: Language) {
  return (
    <section className={`${styles.surface} ${styles.structuredEmptyState}`}>
      <LoaderCircle size={18} className={styles.spinIcon} aria-hidden="true" />
      <div>
        <h3>{lang === "zh" ? "正在加载自进化工作台" : "Loading self-evolution workspace"}</h3>
        <p>
          {lang === "zh"
            ? "监督进化工作台已先保持可用，自进化面板正在按需载入。"
            : "The supervised workspace stays available while the self-evolution panel loads on demand."}
        </p>
      </div>
    </section>
  );
}

export function EvolutionSelfTrackBoundary({
  lang,
  overview,
  worktreeRun,
  observationRun,
  autonomousRun,
  goalInput,
  onGoalInputChange,
  onStartRun,
  onAutonomousAction,
  onStartObservation,
  onTerminateObservation,
  onWorktreeAction,
  onDeleteHistoryGroups,
  startPending,
  observationStartPending,
  observationActionPending,
  worktreeActionPending,
  autonomousActionPending,
  deleteHistoryPending,
  startWorktreeError,
  observationStartError,
  observationActionError,
  worktreeActionError,
  autonomousActionError,
  deleteHistoryError,
  actionFeedback,
  runLocked,
  worktreeRunLocked,
  transactions,
  loading,
}: EvolutionSelfTrackBoundaryProps) {
  return (
    <div className={styles.selfModeStack}>
      <Suspense fallback={selfTrackFallback(lang)}>
        <LazySelfEvolutionTrack
          overview={overview}
          worktreeRun={worktreeRun}
          observationRun={observationRun}
          autonomousRun={autonomousRun}
          goalInput={goalInput}
          onGoalInputChange={onGoalInputChange}
          onStartRun={onStartRun}
          onAutonomousAction={onAutonomousAction}
          onStartObservation={onStartObservation}
          onTerminateObservation={onTerminateObservation}
          onWorktreeAction={onWorktreeAction}
          onDeleteHistoryGroups={onDeleteHistoryGroups}
          startPending={startPending}
          observationStartPending={observationStartPending}
          observationActionPending={observationActionPending}
          worktreeActionPending={worktreeActionPending}
          autonomousActionPending={autonomousActionPending}
          deleteHistoryPending={deleteHistoryPending}
          startWorktreeError={startWorktreeError}
          observationStartError={observationStartError}
          observationActionError={observationActionError}
          worktreeActionError={worktreeActionError}
          autonomousActionError={autonomousActionError}
          deleteHistoryError={deleteHistoryError}
          actionFeedback={actionFeedback}
          runLocked={runLocked}
          worktreeRunLocked={worktreeRunLocked}
          transactions={transactions}
          loading={loading}
        />
      </Suspense>
    </div>
  );
}
