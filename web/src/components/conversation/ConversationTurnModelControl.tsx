import { Bot } from "lucide-react";

import type { SessionLlmModelOption } from "../../api/types";
import { useAppI18n } from "../../i18n/useAppI18n";
import { VTooltip } from "../vui";
import styles from "./ConversationTurnModelControl.styles";

type ConversationTurnModelControlProps = {
  /** The current Agent-bound dialogue model; never a composer override. */
  model: SessionLlmModelOption | null;
  loading?: boolean;
  error?: boolean;
};

/** Read-only model identity. Binding changes belong to Agent management. */
export function ConversationTurnModelControl({ model, loading = false, error = false }: ConversationTurnModelControlProps) {
  const { lang } = useAppI18n({ domains: ["chat"] });
  const zh = lang === "zh";
  const label = error
    ? (zh ? "模型读取失败" : "Model unavailable")
    : loading
      ? (zh ? "读取模型…" : "Loading model…")
      : model?.label || model?.model || model?.modelRef || model?.modelId || (zh ? "未绑定模型" : "No model bound");
  const hint = zh ? "模型由 Agent 配置决定，请到 Agent 管理页修改" : "The model is configured in Agent management.";
  return (
    <VTooltip content={`${label} · ${hint}`}>
      <span
        className={styles.root}
        data-testid="conversation-turn-model-control"
        data-vui="conversation-agent-model-display"
        aria-label={`${zh ? "Agent 模型" : "Agent model"}: ${label}`}
        aria-busy={loading || undefined}
        title={`${label} · ${hint}`}
      >
        <Bot className={styles.icon} size={12} aria-hidden="true" />
        <span className={styles.label}>{label}</span>
      </span>
    </VTooltip>
  );
}
