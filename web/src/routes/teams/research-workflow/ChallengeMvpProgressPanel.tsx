/**
 * MVP acceptance progress for the research workflow workspace.
 *
 * Read-only projection of challenge-question run facts (machine validation,
 * human gates, completion) from the backend summary — never a second writer.
 * Question rows open the single-question acceptance detail via deep link.
 */
import { useQuery } from "@tanstack/react-query";

import { getChallengeQuestionRunStatus } from "../../../api/challengeQuestionRuns";
import { queryKeys } from "../../../api/queryKeys";
import {
  VButton,
  VEmptyState,
  VStateSurface,
  VSurface,
} from "../../../components/vui";
import styles from "./ChallengeMvpProgressPanel.styles";

export type ChallengeMvpProgressPanelProps = {
  teamId: string;
  lang?: "zh" | "en";
  onOpenQuestion: (questionId: string) => void;
};

export function ChallengeMvpProgressPanel({
  teamId,
  lang = "zh",
  onOpenQuestion,
}: ChallengeMvpProgressPanelProps) {
  const zh = lang === "zh";
  const statusQuery = useQuery({
    queryKey: queryKeys.challengeQuestionRunStatus(teamId),
    queryFn: () => getChallengeQuestionRunStatus(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 30_000,
  });

  if (statusQuery.isPending) {
    return (
      <VSurface tone="panel" className={styles.root}>
        <VStateSurface tone="loading" title={zh ? "读取题目进度" : "Loading question progress"} fill className={styles.fill} />
      </VSurface>
    );
  }

  if (statusQuery.isError || !statusQuery.data) {
    return (
      <VSurface tone="panel" className={styles.root}>
        <div
          className={styles.error}
          role="alert"
        >
          {statusQuery.error instanceof Error ? statusQuery.error.message : String(statusQuery.error)}
        </div>
        <VButton type="button" variant="secondary" onClick={() => void statusQuery.refetch()}>
          {zh ? "重试" : "Retry"}
        </VButton>
      </VSurface>
    );
  }

  const summary = statusQuery.data.summary;
  const results = summary.validatedQuestionResults ?? [];

  return (
    <VSurface tone="panel" className={styles.root} data-vui="mvp-progress-panel">
      <div className={styles.header}>
        <div className={styles.eyebrow}>
          {zh ? "MVP 验收进度" : "MVP acceptance"}
        </div>
        <VButton type="button" variant="ghost" onClick={() => void statusQuery.refetch()}>
          {zh ? "刷新" : "Refresh"}
        </VButton>
      </div>
      <div className={styles.metrics}>
        <div className={styles.metric}>
          <div className={styles.metricLabel}>{zh ? "有效候选" : "Valid"}</div>
          <div className={styles.metricValue}>{summary.validCandidateCount}</div>
        </div>
        <div className={styles.metric}>
          <div className={styles.metricLabel}>{zh ? "已验证题" : "Validated"}</div>
          <div className={styles.metricValue}>{summary.validatedQuestionCount}</div>
        </div>
        <div className={styles.metric}>
          <div className={styles.metricLabel}>{zh ? "已批准" : "Approved"}</div>
          <div className={styles.metricValue}>{summary.completedCount}</div>
        </div>
      </div>

      {results.length === 0 ? (
        <VEmptyState title={zh ? "暂无已验证题目" : "No validated questions"} className={styles.empty}>
          {zh ? "完成受控运行与候选晋升后，题目结果会出现在这里。" : "Question results appear here after controlled runs and candidate promotion."}
        </VEmptyState>
      ) : (
        <ul className={styles.list}>
          {results.map((item) => (
            <li
              key={item.questionId}
              className={styles.item}
            >
              <div className={styles.itemText}>
                <div className={styles.itemTitle}>{item.questionId}</div>
                <div className={styles.itemMeta}>
                  {item.runId} · {item.status}
                </div>
              </div>
              <VButton
                type="button"
                variant="ghost"
                onClick={() => onOpenQuestion(item.questionId)}
              >
                {zh ? "详情" : "Detail"}
              </VButton>
            </li>
          ))}
        </ul>
      )}
    </VSurface>
  );
}
