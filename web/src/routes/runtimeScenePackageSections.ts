import type { RuntimeSceneDetail, RuntimeSceneRawFile } from "../api/types";

export type RuntimeScenePackageSectionId =
  | "conversations"
  | "supervised"
  | "selfEvolution"
  | "agent"
  | "raw"
  | "artifacts";

export type RuntimeScenePackageSection = {
  id: RuntimeScenePackageSectionId;
  titleZh: string;
  titleEn: string;
  emptyZh: string;
  emptyEn: string;
  files: RuntimeSceneRawFile[];
};

function byPath(left: RuntimeSceneRawFile, right: RuntimeSceneRawFile) {
  return left.path.localeCompare(right.path);
}

function isSupervisedFile(file: RuntimeSceneRawFile) {
  return file.path.startsWith("agent/supervised_runs/") || file.path.startsWith("artifacts/supervised/");
}

function isSelfEvolutionFile(file: RuntimeSceneRawFile) {
  return file.path.startsWith("agent/self_evolution_runs/") || file.path.startsWith("artifacts/self_evolution/");
}

export function runtimeScenePackageSections(scene: RuntimeSceneDetail): RuntimeScenePackageSection[] {
  const conversationLogs = [...scene.conversationLogs].sort(byPath);
  const rawFiles = [...scene.rawFiles].sort(byPath);
  const supervisedLogs = [...scene.agentLogs.filter(isSupervisedFile), ...scene.artifacts.filter(isSupervisedFile)].sort(
    byPath,
  );
  const selfEvolutionLogs = [
    ...scene.agentLogs.filter(isSelfEvolutionFile),
    ...scene.artifacts.filter(isSelfEvolutionFile),
  ].sort(byPath);
  const agentLogs = scene.agentLogs
    .filter((file) => !isSupervisedFile(file) && !isSelfEvolutionFile(file))
    .sort(byPath);
  const artifacts = scene.artifacts
    .filter((file) => !isSupervisedFile(file) && !isSelfEvolutionFile(file))
    .sort(byPath);

  return [
    {
      id: "conversations",
      titleZh: "对话日志",
      titleEn: "Conversations",
      emptyZh: "本周期没有对话消息。",
      emptyEn: "No conversation messages were recorded in this cycle.",
      files: conversationLogs,
    },
    {
      id: "supervised",
      titleZh: "监督进化",
      titleEn: "Supervised Evolution",
      emptyZh: "本周期没有启动监督进化。",
      emptyEn: "No supervised evolution run was started in this cycle.",
      files: supervisedLogs,
    },
    {
      id: "selfEvolution",
      titleZh: "无监督进化",
      titleEn: "Self Evolution",
      emptyZh: "本周期没有启动无监督进化。",
      emptyEn: "No self-evolution run was started in this cycle.",
      files: selfEvolutionLogs,
    },
    {
      id: "agent",
      titleZh: "Agent 运行",
      titleEn: "Agent Runtime",
      emptyZh: "本周期没有其他 Agent 运行子日志。",
      emptyEn: "No other agent runtime child logs were recorded in this cycle.",
      files: agentLogs,
    },
    {
      id: "raw",
      titleZh: "系统原始日志",
      titleEn: "System Raw Logs",
      emptyZh: "本周期没有系统原始日志。",
      emptyEn: "No system raw logs were recorded in this cycle.",
      files: rawFiles,
    },
    {
      id: "artifacts",
      titleZh: "产物",
      titleEn: "Artifacts",
      emptyZh: "本周期没有产物文件。",
      emptyEn: "No artifacts were recorded in this cycle.",
      files: artifacts,
    },
  ];
}

export function runtimeScenePackageFiles(scene: RuntimeSceneDetail): RuntimeSceneRawFile[] {
  return runtimeScenePackageSections(scene).flatMap((section) => section.files);
}
