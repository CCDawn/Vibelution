import { VMetricStrip, VTooltip } from "../components/vui";
import styles from "./MemoryKnowledgePipelinePanel.styles";

export type MemoryKnowledgePipelinePanelCopy = {
  knowledgeBases: string;
  pendingProposals: string;
  formalKnowledge: string;
  sourceArtifacts: string;
  platformPipeline: string;
  knowledgeSubtitle: string;
  teamKnowledgeDomain: string;
  toolReadableOnly: string;
  promptBoundary: string;
  governance: string;
  pipelineSource: string;
  pipelineProposal: string;
  pipelineBatch: string;
  pipelineFormal: string;
  pipelineRating: string;
};

type MemoryKnowledgePipelinePanelProps = {
  copy: MemoryKnowledgePipelinePanelCopy;
  knowledgeBaseCount: number;
  pendingProposalCount: number;
  itemCount: number;
  sourceArtifactCount: number;
  batchCount: number;
  pendingRatingSuggestionCount: number;
};

export function MemoryKnowledgePipelinePanel({
  copy,
  knowledgeBaseCount,
  pendingProposalCount,
  itemCount,
  sourceArtifactCount,
  batchCount,
  pendingRatingSuggestionCount,
}: MemoryKnowledgePipelinePanelProps) {
  const pipelineSteps = [
    { label: copy.pipelineSource, value: sourceArtifactCount },
    { label: copy.pipelineProposal, value: pendingProposalCount },
    { label: copy.pipelineBatch, value: batchCount },
    { label: copy.pipelineFormal, value: itemCount },
    { label: copy.pipelineRating, value: pendingRatingSuggestionCount },
  ];

  return (
    <>
      <div className={styles.summaryGrid}>
        <VMetricStrip
          ariaLabel={copy.platformPipeline}
          metrics={[
            { id: "bases", label: copy.knowledgeBases, value: knowledgeBaseCount },
            { id: "proposals", label: copy.pendingProposals, value: pendingProposalCount },
            { id: "items", label: copy.formalKnowledge, value: itemCount },
            { id: "artifacts", label: copy.sourceArtifacts, value: sourceArtifactCount },
          ]}
        />
      </div>
      <VTooltip content={copy.knowledgeSubtitle} width="wide">
        <section
          className={styles.pipelinePanel}
          aria-label={`${copy.platformPipeline} · ${copy.knowledgeSubtitle}`}
          tabIndex={0}
        >
          <div className={styles.pipelineHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.platformPipeline}</p>
              <h2>{copy.teamKnowledgeDomain}</h2>
            </div>
            <div className={styles.pipelineBoundary}>
              <span>{copy.toolReadableOnly}</span>
              <span>{copy.promptBoundary}</span>
              <span>{copy.governance}</span>
            </div>
          </div>
          <div className={styles.pipelineSteps}>
            {pipelineSteps.map((step, index) => (
              <div key={step.label} className={styles.pipelineStep}>
                <span className={styles.pipelineIndex}>{index + 1}</span>
                <strong>{step.value}</strong>
                <span>{step.label}</span>
              </div>
            ))}
          </div>
        </section>
      </VTooltip>
    </>
  );
}
