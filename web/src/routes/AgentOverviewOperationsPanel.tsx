import { Activity, ExternalLink, FileSearch, PlayCircle } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./AgentOverviewOperationsPanel.styles";

export type AgentOverviewOperationsCopy = {
  currentFocus: string;
  recentActivity: string;
  loading: string;
  noActivity: string;
  noActivityDetail: string;
  activityUnavailable: string;
  latestRun: string;
  updated: string;
  nextStep: string;
  openSession: string;
  openLogs: string;
  checkConfig: string;
  viewActivity: string;
};

export type AgentOverviewRuntimeView = {
  statusLabel: string;
  statusReason: string;
  summary: string;
  latestRunId: string;
  updatedAt: string;
  nextStep: string;
  onOpenSession?: () => void;
  onOpenLogs?: () => void;
};

export type AgentOverviewActivityView = {
  id: string;
  title: string;
  body: string;
  meta: string;
  onOpenLogs?: () => void;
};

export type AgentOverviewOperationsPanelProps = {
  copy: AgentOverviewOperationsCopy;
  state: "loading" | "ready" | "error";
  errorMessage?: string;
  runtime: AgentOverviewRuntimeView;
  activities: AgentOverviewActivityView[];
  onOpenActivity: () => void;
  onOpenConfig: () => void;
  onOpenSession?: () => void;
};

export function AgentOverviewOperationsPanel({
  copy,
  state,
  errorMessage,
  runtime,
  activities,
  onOpenActivity,
  onOpenConfig,
  onOpenSession,
}: AgentOverviewOperationsPanelProps) {
  const sessionAction = runtime.onOpenSession || onOpenSession;

  return (
    <div className={styles.operationsGrid}>
      <section className={styles.section} aria-label={copy.currentFocus}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.eyebrow}>{copy.currentFocus}</p>
            <h3 className={styles.title}>{runtime.statusLabel}</h3>
          </div>
          <span className={styles.runtimePill}>{runtime.statusReason}</span>
        </div>
        <p className={styles.runtimeSummary}>{runtime.summary}</p>
        <div className={styles.runtimeMeta}>
          <span>
            <strong>{copy.latestRun}</strong>
            <small title={runtime.latestRunId}>{runtime.latestRunId}</small>
          </span>
          <span>
            <strong>{copy.updated}</strong>
            <small>{runtime.updatedAt}</small>
          </span>
        </div>
        <div className={styles.nextStep}>
          <strong>{copy.nextStep}</strong>
          <span>{runtime.nextStep}</span>
        </div>
        <div className={styles.actions}>
          {sessionAction ? (
            <VButton type="button" variant="secondary" icon={<ExternalLink size={13} />} onPress={sessionAction}>
              {copy.openSession}
            </VButton>
          ) : null}
          {runtime.onOpenLogs ? (
            <VButton type="button" variant="ghost" icon={<FileSearch size={13} />} onPress={runtime.onOpenLogs}>
              {copy.openLogs}
            </VButton>
          ) : null}
        </div>
      </section>

      <section className={styles.section} aria-label={copy.recentActivity}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.eyebrow}>{copy.recentActivity}</p>
            <h3 className={styles.title}>{activities.length ? `${activities.length} 条更新` : copy.noActivity}</h3>
          </div>
          <Activity size={16} aria-hidden="true" />
        </div>
        <div className={styles.activityBody} aria-busy={state === "loading"}>
          {state === "loading" ? (
            <div className={styles.state}>
              <div className={styles.stateInner}>
                <PlayCircle size={20} aria-hidden="true" />
                <strong>{copy.loading}</strong>
              </div>
            </div>
          ) : null}
          {state === "error" ? (
            <div className={styles.state}>
              <div className={styles.stateInner}>
                <strong>{copy.activityUnavailable}</strong>
                <p className={styles.error} role="alert">{errorMessage || copy.activityUnavailable}</p>
                <VButton type="button" variant="ghost" onPress={onOpenActivity}>{copy.viewActivity}</VButton>
              </div>
            </div>
          ) : null}
          {state === "ready" && activities.length ? (
            <div className={styles.activityList}>
              {activities.map((activity) => (
                <article key={activity.id} className={styles.activityItem}>
                  <div className={styles.activityText}>
                    <strong>{activity.title}</strong>
                    <p>{activity.body}</p>
                    <small>{activity.meta}</small>
                  </div>
                  {activity.onOpenLogs ? (
                    <VButton
                      type="button"
                      variant="ghost"
                      className={styles.activityAction}
                      aria-label={`${copy.openLogs}: ${activity.title}`}
                      onPress={activity.onOpenLogs}
                    >
                      {copy.openLogs}
                    </VButton>
                  ) : null}
                </article>
              ))}
            </div>
          ) : null}
          {state === "ready" && !activities.length ? (
            <div className={styles.state}>
              <div className={styles.stateInner}>
                <PlayCircle size={20} aria-hidden="true" />
                <strong>{copy.noActivity}</strong>
                <p>{copy.noActivityDetail}</p>
                <div className={styles.actions}>
                  {sessionAction ? (
                    <VButton type="button" variant="secondary" onPress={sessionAction}>{copy.openSession}</VButton>
                  ) : null}
                  <VButton type="button" variant="ghost" onPress={onOpenConfig}>{copy.checkConfig}</VButton>
                </div>
              </div>
            </div>
          ) : null}
        </div>
        {state === "ready" && activities.length ? (
          <div className={styles.actions}>
            <VButton type="button" variant="ghost" onPress={onOpenActivity}>{copy.viewActivity}</VButton>
          </div>
        ) : null}
      </section>
    </div>
  );
}
