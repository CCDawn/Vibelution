import { Brain, CheckCircle2, Copy as CopyIcon, Eye, FileText, Link2, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import type { MemoryItem, MemorySection } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./MemoryRoute.styles";

type MemoryDetailPanelCopy = {
  title: string;
  loading: string;
  loadFailed: string;
  noMatches: string;
  noContent: string;
  inPrompt: string;
  canUse: string;
  manualOnly: string;
  impact: string;
  copySourceSummary: string;
  copySourcePath: string;
  copyRawContentAction: string;
  copyCurrentLink: string;
  sourcePath: string;
  sourceApi: string;
  agentVisible: string;
  runtimeInjected: string;
  yes: string;
  no: string;
  agentVisibility: string;
  summary: string;
  rawContent: string;
  generatedAt: string;
};

type MemoryDetailImpact = {
  title: string;
  body: string;
};

type MemoryDetailChannelPill = {
  label: string;
  hint: string;
};

type MemoryDetailFeedback = {
  tone: "idle" | "success" | "error";
  text: string;
};

type MemoryDetailPanelProps = {
  copy: MemoryDetailPanelCopy;
  showEditor: boolean;
  managementEditor: ReactNode;
  section: MemorySection | null;
  item: MemoryItem | null;
  activeImpact: MemoryDetailImpact | null;
  channelPills: MemoryDetailChannelPill[];
  copyFeedback: MemoryDetailFeedback;
  canCopyRawContent: boolean;
  isDetailFetching: boolean;
  detailErrorText: string;
  isEditing: boolean;
  overviewIsPending: boolean;
  sectionUpdatedAt: string;
  generatedAt: string;
  onCopySourceSummary: () => void;
  onCopySourcePath: () => void;
  onCopyRawContent: () => void;
  onCopyCurrentLink: () => void;
};

function statusClassName(active: boolean, injected: boolean) {
  if (injected) {
    return `${styles.statusPill} ${styles.statusPillPrompt}`;
  }
  if (active) {
    return `${styles.statusPill} ${styles.statusPillVisible}`;
  }
  return `${styles.statusPill} ${styles.statusPillMuted}`;
}

function contentLanguage(contentType: string) {
  if (contentType === "json") {
    return "json";
  }
  if (contentType === "markdown") {
    return "markdown";
  }
  if (contentType === "html") {
    return "html";
  }
  return "text";
}

export function MemoryDetailPanel({
  copy,
  showEditor,
  managementEditor,
  section,
  item,
  activeImpact,
  channelPills,
  copyFeedback,
  canCopyRawContent,
  isDetailFetching,
  detailErrorText,
  isEditing,
  overviewIsPending,
  sectionUpdatedAt,
  generatedAt,
  onCopySourceSummary,
  onCopySourcePath,
  onCopyRawContent,
  onCopyCurrentLink,
}: MemoryDetailPanelProps) {
  return (
    <aside className={showEditor ? styles.detailPanel : `${styles.detailPanel} ${styles.manageDetailPanel}`}>
      {showEditor ? managementEditor : null}

      {item && section ? (
        <>
          <section className={styles.detailHeader}>
            <div>
              <p className={styles.panelEyebrow}>{section.title}</p>
              <h2>{item.title}</h2>
              <p>{item.summary}</p>
            </div>
            <span className={statusClassName(item.agentVisible, item.inPrompt)}>
              {item.inPrompt ? copy.inPrompt : item.agentVisible ? copy.canUse : copy.manualOnly}
            </span>
          </section>

          {activeImpact ? (
            <section className={styles.impactPanel}>
              <div className={styles.visibilityHeader}>
                <Brain size={16} />
                <div>
                  <strong>{copy.impact}</strong>
                  <p>{activeImpact.title}</p>
                </div>
              </div>
              <p>{activeImpact.body}</p>
            </section>
          ) : null}

          <div className={styles.detailActions}>
            <VButton type="button" className={styles.detailActionButton} onClick={onCopySourceSummary}>
              <CopyIcon size={14} />
              <span>{copy.copySourceSummary}</span>
            </VButton>
            <VButton type="button" className={styles.detailActionButton} onClick={onCopySourcePath}>
              <FileText size={14} />
              <span>{copy.copySourcePath}</span>
            </VButton>
            <VButton
              type="button"
              className={styles.detailActionButton}
              onClick={onCopyRawContent}
              isDisabled={!canCopyRawContent}
              title={!canCopyRawContent ? copy.noContent : undefined}
            >
              <FileText size={14} />
              <span>{copy.copyRawContentAction}</span>
            </VButton>
            <VButton type="button" className={styles.detailActionButton} onClick={onCopyCurrentLink}>
              <Link2 size={14} />
              <span>{copy.copyCurrentLink}</span>
            </VButton>
          </div>

          {copyFeedback.tone !== "idle" ? (
            <p className={styles.copyNotice} data-tone={copyFeedback.tone}>
              {copyFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
              <span>{copyFeedback.text}</span>
            </p>
          ) : null}

          <div className={styles.factGrid}>
            <section>
              <span>{copy.sourcePath}</span>
              <strong title={item.path}>{item.path || "-"}</strong>
            </section>
            <section>
              <span>{copy.sourceApi}</span>
              <strong title={section.sourceApi}>{section.sourceApi || "-"}</strong>
            </section>
            <section>
              <span>{copy.agentVisible}</span>
              <strong>{item.agentVisible ? copy.yes : copy.no}</strong>
            </section>
            <section>
              <span>{copy.runtimeInjected}</span>
              <strong>{item.inPrompt ? copy.yes : copy.no}</strong>
            </section>
          </div>

          <section className={styles.visibilityPanel}>
            <div className={styles.visibilityHeader}>
              <Eye size={16} />
              <div>
                <strong>{copy.agentVisibility}</strong>
                <p>{section.agentVisibility}</p>
              </div>
            </div>
            <div className={styles.usageList}>
              {channelPills.map((pill) => (
                <span key={`${item.id}:channel:${pill.label}`} title={pill.hint}>
                  <CheckCircle2 size={13} />
                  {pill.label}
                </span>
              ))}
            </div>
            <div className={styles.usageList}>
              {item.usedBy.map((usage) => (
                <span key={`${item.id}:${usage}`}>
                  <CheckCircle2 size={13} />
                  {usage}
                </span>
              ))}
            </div>
          </section>

          <section className={styles.sectionPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.summary}</p>
                <h3>{section.sourceKind}</h3>
              </div>
              <span className={styles.countPill}>{sectionUpdatedAt}</span>
            </div>
            <p>{section.summary}</p>
          </section>

          <details className={styles.rawPanel} open={showEditor}>
            <summary>
              <FileText size={15} />
              <span>{copy.rawContent}</span>
              <code>{item.contentType}</code>
            </summary>
            {isDetailFetching ? <p>{copy.loading}</p> : null}
            {detailErrorText ? <p>{copy.loadFailed}: {detailErrorText}</p> : null}
            {item.content ? (
              <pre data-language={contentLanguage(item.contentType)}>{item.content}</pre>
            ) : !isDetailFetching ? (
              <p>{copy.noContent}</p>
            ) : null}
          </details>
        </>
      ) : isEditing ? null : (
        <section className={styles.emptyDetail}>
          <Brain size={24} />
          <strong>{copy.title}</strong>
          <p>{overviewIsPending ? copy.loading : copy.noMatches}</p>
        </section>
      )}

      {generatedAt ? (
        <p className={styles.generatedAt}>
          {copy.generatedAt}: {generatedAt}
        </p>
      ) : null}
    </aside>
  );
}
