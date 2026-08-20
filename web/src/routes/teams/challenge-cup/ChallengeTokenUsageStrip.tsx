import { VMetricStrip } from "../../../components/vui";

import {
  tokenUsageCountLabel,
  type TokenUsageAnomaly,
  type TokenUsageQuestion,
} from "./challengeTokenUsageModel";
import styles from "./ChallengeTokenUsageStrip.styles";

export function ChallengeTokenUsageStrip({
  lang = "zh",
  totalTokens,
  callCount,
  inputTokens,
  outputTokens,
  anomaly,
  title,
}: {
  lang?: "zh" | "en";
  totalTokens: number;
  callCount: number;
  inputTokens: number;
  outputTokens: number;
  anomaly?: TokenUsageAnomaly | null;
  title?: string;
}) {
  const zh = lang === "zh";
  return (
    <section className={styles.root} data-testid="challenge-token-usage" data-vui="challenge-token-usage">
      <VMetricStrip
        ariaLabel={title || (zh ? "模型 token 消耗" : "Model token usage")}
        metrics={[
          { id: "tokens", label: zh ? "token 计" : "Token count", value: totalTokens, tone: "info" },
          { id: "calls", label: zh ? "调用次数" : "Calls", value: callCount },
          { id: "input", label: zh ? "输入" : "Input", value: inputTokens },
          { id: "output", label: zh ? "输出" : "Output", value: outputTokens },
        ]}
      />
      <div className={styles.note}>{tokenUsageCountLabel(totalTokens, callCount, zh)}</div>
      {anomaly ? (
        <div className={styles.anomaly} role="status" data-testid="challenge-token-usage-anomaly">
          {anomaly.message}
        </div>
      ) : null}
    </section>
  );
}

export function ChallengeQuestionTokenUsage({
  lang = "zh",
  usage,
}: {
  lang?: "zh" | "en";
  usage: TokenUsageQuestion | null;
}) {
  const zh = lang === "zh";
  const stages = usage?.stages ?? [];
  return (
    <details className={styles.details} data-testid="challenge-question-token-usage">
      <summary>{zh ? "本题 token 消耗" : "Question token usage"}</summary>
      <ChallengeTokenUsageStrip
        lang={lang}
        title={zh ? "本题 token 消耗" : "Question token usage"}
        totalTokens={usage?.totalTokens ?? 0}
        callCount={usage?.callCount ?? 0}
        inputTokens={usage?.inputTokens ?? 0}
        outputTokens={usage?.outputTokens ?? 0}
        anomaly={usage?.anomaly}
      />
      {stages.length > 0 ? (
        <ul className={styles.stages}>
          {stages.map((stage) => (
            <li key={stage.stageId}>
              {stage.stageId}: {stage.totalTokens} token · {stage.callCount}
              {zh ? " 次" : " calls"}
            </li>
          ))}
        </ul>
      ) : null}
    </details>
  );
}
