export type KnowledgePackageReading = {
  artifactId: string;
  status: "available" | "unavailable";
  title: string;
  summary: string;
  content: string;
  sourceUrl: string;
  riskSummary: string;
  uncertainties: string[];
};

export type ResearchHandoffReading = {
  runId: string;
  teamId: string;
  knowledgePackages: KnowledgePackageReading[];
};
