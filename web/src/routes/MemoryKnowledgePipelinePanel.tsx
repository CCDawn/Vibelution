import styles from "./MemoryRoute.styles";

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
        <section className={styles.summaryCard}>
          <span>{copy.knowledgeBases}</span>
          <strong>{knowledgeBaseCount}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.pendingProposals}</span>
          <strong>{pendingProposalCount}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.formalKnowledge}</span>
          <strong>{itemCount}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.sourceArtifacts}</span>
          <strong>{sourceArtifactCount}</strong>
        </section>
      </div>
      <section className={styles.pipelinePanel} aria-label={copy.platformPipeline} title={copy.knowledgeSubtitle}>
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
    </>
  );
}
