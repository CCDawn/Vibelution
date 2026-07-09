import type { SessionLlmPayloadTrace } from "../../api/types";
import styles from "../ChatCodingRoute.styles";

type LlmPayloadTracePanelProps = {
  lang: "zh" | "en";
  trace: SessionLlmPayloadTrace | null | undefined;
};

type TraceRow = {
  key: string;
  label: string;
  value: string;
};

function safeText(value: unknown): string {
  return String(value ?? "").trim();
}

function safeCount(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(Math.max(0, value)) : "";
}

function safeBoolLabel(value: unknown, lang: "zh" | "en"): string {
  if (value === true) {
    return lang === "zh" ? "开启" : "on";
  }
  if (value === false) {
    return lang === "zh" ? "关闭" : "off";
  }
  return "";
}

function compactRows(trace: SessionLlmPayloadTrace, lang: "zh" | "en"): TraceRow[] {
  const protocol = safeText(trace.selectedProtocol) || safeText(trace.transport);
  const cacheMode = safeText(trace.promptCache?.promptCacheMode);
  const thinkingType = safeText(trace.thinking?.thinkingType);
  const thinkingRequested = safeBoolLabel(trace.thinking?.thinkingRequested, lang);
  const thinking = thinkingType || thinkingRequested;
  const messageCount = safeCount(trace.messageCount);
  const toolCount = safeCount(trace.toolCount);
  const imageBlockCount = safeCount(trace.imageBlockCount);
  const mediaShape = [
    toolCount ? `${lang === "zh" ? "工具" : "tools"} ${toolCount}` : "",
    imageBlockCount ? `${lang === "zh" ? "图像" : "images"} ${imageBlockCount}` : "",
  ].filter(Boolean).join(" / ");

  return [
    { key: "provider", label: lang === "zh" ? "Provider" : "Provider", value: safeText(trace.provider) },
    { key: "model", label: lang === "zh" ? "模型" : "Model", value: safeText(trace.model) },
    { key: "protocol", label: lang === "zh" ? "协议" : "Protocol", value: protocol },
    { key: "chain", label: lang === "zh" ? "链路" : "Chain", value: safeText(trace.dialogueChainMode) },
    { key: "messages", label: lang === "zh" ? "消息" : "Messages", value: messageCount },
    { key: "shape", label: lang === "zh" ? "载荷" : "Payload", value: mediaShape },
    { key: "cache", label: lang === "zh" ? "缓存" : "Cache", value: cacheMode },
    { key: "thinking", label: lang === "zh" ? "思考" : "Thinking", value: thinking },
  ].filter((row) => row.value);
}

export function LlmPayloadTracePanel({ lang, trace }: LlmPayloadTracePanelProps) {
  if (!trace) {
    return null;
  }
  const rows = compactRows(trace, lang);
  if (!rows.length) {
    return null;
  }
  const title = lang === "zh" ? "模型载荷" : "LLM payload";
  const subtitle = safeText(trace.traceId) || safeText(trace.turnId) || safeText(trace.recordedAt);

  return (
    <section className={`${styles.leftBlock} ${styles.llmPayloadTracePanel}`} role="status" aria-live="polite" aria-label={title}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionIdentity}>
          <p className={styles.blockEyebrow}>LLM</p>
          <h3 className={styles.sectionTitle}>{title}</h3>
          {subtitle ? <p className={styles.sectionMetaLine}>{subtitle}</p> : null}
        </div>
      </div>
      <div className={styles.llmPayloadTraceGrid}>
        {rows.map((row) => (
          <div key={row.key} className={styles.llmPayloadTraceItem} title={`${row.label}: ${row.value}`}>
            <span className={styles.llmPayloadTraceMuted}>{row.label}</span>
            <strong>{row.value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
