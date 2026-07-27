import { ChevronRight } from "lucide-react";

import type {
  SessionAgentPromptSnapshot,
  SessionPromptAssemblyManifest,
  SessionPromptAssemblySegment,
} from "../../api/types";
import styles from "./ChatPromptAssemblyInspector.styles";

type ChatPromptAssemblyInspectorProps = {
  lang: "zh" | "en";
  snapshot: SessionAgentPromptSnapshot;
  manifest?: SessionPromptAssemblyManifest;
};

function safeText(value: unknown): string {
  return String(value ?? "").trim();
}

function safeCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;
}

function decisionLabel(segment: SessionPromptAssemblySegment, lang: "zh" | "en"): string {
  const decision = safeText(segment.decision);
  const labels: Record<string, [string, string]> = {
    full: ["完整", "Full"],
    truncated: ["已截断", "Truncated"],
    index_only: ["仅索引", "Index only"],
    omitted: ["已省略", "Omitted"],
    blocked: ["已阻止", "Blocked"],
  };
  const label = labels[decision];
  return label ? label[lang === "zh" ? 0 : 1] : decision || (lang === "zh" ? "未知" : "Unknown");
}

function hashLabel(value: unknown): string {
  const text = safeText(value);
  return text.length > 14 ? `${text.slice(0, 14)}…` : text || "—";
}

export function ChatPromptAssemblyInspector({
  lang,
  snapshot,
  manifest: runtimeManifest,
}: ChatPromptAssemblyInspectorProps) {
  const manifest = runtimeManifest ?? snapshot.promptAssembly;
  const title = lang === "zh" ? "Prompt 装配" : "Prompt assembly";
  if (!manifest) {
    return (
      <details className={`group ${styles.root}`}>
        <summary className={styles.summary}>
          <span className={styles.titleGroup}>
            <ChevronRight aria-hidden="true" className={styles.chevron} />
            <span className={styles.title}>{title} · {lang === "zh" ? "旧快照" : "Legacy snapshot"}</span>
          </span>
        </summary>
        <div className={styles.body}>
          <p className={styles.legacy}>
            {lang === "zh"
              ? "旧会话未记录装配清单；系统不会为展示诊断信息而重建或改写 Prompt。"
              : "This legacy session did not record an assembly manifest. Its prompt is not rebuilt or rewritten for diagnostics."}
          </p>
        </div>
      </details>
    );
  }

  const segments = Array.isArray(manifest.segments) ? manifest.segments : [];
  const usedTokens = safeCount(manifest.totalEstimatedTokens);
  const budgetTokens = safeCount(manifest.budgetTokens);
  const tokenSummary = `${usedTokens} / ${budgetTokens || "—"} tokens`;

  return (
    <details className={`group ${styles.root}`}>
      <summary className={styles.summary}>
        <span className={styles.titleGroup}>
          <ChevronRight aria-hidden="true" className={styles.chevron} />
          <span className={styles.title}>{title}</span>
          <span className={styles.summaryMeta}>{safeText(manifest.assemblyMode) || "v2"}</span>
        </span>
        <span className={styles.summaryMeta}>{tokenSummary} · {segments.length} {lang === "zh" ? "段" : "segments"}</span>
      </summary>
      <div className={styles.body}>
        <div className={styles.facts}>
          <div className={styles.fact}>
            <span className={styles.label}>{lang === "zh" ? "协议" : "Protocol"}</span>
            <span className={styles.value}>{safeText(manifest.modelProtocol) || "—"}</span>
          </div>
          <div className={styles.fact}>
            <span className={styles.label}>{lang === "zh" ? "稳定前缀" : "Stable prefix"}</span>
            <span className={styles.value} title={safeText(manifest.stablePrefixHash)}>
              {hashLabel(manifest.stablePrefixHash)}
            </span>
          </div>
          <div className={styles.fact}>
            <span className={styles.label}>{lang === "zh" ? "会话快照" : "Session snapshot"}</span>
            <span className={styles.value} title={safeText(manifest.sessionSnapshotHash)}>
              {hashLabel(manifest.sessionSnapshotHash)}
            </span>
          </div>
        </div>
        <div className={styles.segmentList}>
          {segments.map((segment, index) => (
            <div className={styles.segment} key={`${safeText(segment.key) || "segment"}-${index}`}>
              <span className={styles.segmentIdentity} title={safeText(segment.source)}>
                {safeText(segment.key) || (lang === "zh" ? "未命名分段" : "Unnamed segment")}
              </span>
              <span className={styles.tier}>{safeText(segment.tier) || "—"}</span>
              <span className={styles.decision}>{decisionLabel(segment, lang)}</span>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}
