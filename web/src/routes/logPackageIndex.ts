import type { FileTreeNode } from "../api/types";

export type LogPackageFile = {
  name: string;
  path: string;
};

export type LogPackageIndexItem = {
  id: string;
  titleZh: string;
  titleEn: string;
  path: string;
  fileCount: number;
  files: LogPackageFile[];
};

const ROOT_PACKAGE_ID = "__root__";

const PACKAGE_LABELS: Record<string, { zh: string; en: string }> = {
  agent: { zh: "Agent 运行日志", en: "Agent runtime logs" },
  artifacts: { zh: "运行产物", en: "Artifacts" },
  conversation_logs: { zh: "对话日志包", en: "Conversation log packages" },
  conversations: { zh: "对话日志", en: "Conversations" },
  debug: { zh: "调试日志", en: "Debug logs" },
  events: { zh: "结构化事件", en: "Structured events" },
  harness_reports: { zh: "测试运行报告", en: "Harness reports" },
  raw: { zh: "系统原始日志", en: "System raw logs" },
  runtime_scenes: { zh: "运行现场日志包", en: "Runtime scene packages" },
  self_evolution: { zh: "无监督进化日志", en: "Self-evolution logs" },
  self_evolution_runs: { zh: "无监督进化运行", en: "Self-evolution runs" },
  supervised: { zh: "监督进化日志", en: "Supervised evolution logs" },
  supervised_runs: { zh: "监督进化运行", en: "Supervised runs" },
};

function collectFiles(nodes: FileTreeNode[]): LogPackageFile[] {
  const files: LogPackageFile[] = [];
  for (const node of nodes) {
    if (node.type === "file") {
      files.push({ name: node.name, path: node.path });
      continue;
    }
    files.push(...collectFiles(node.children ?? []));
  }
  return files.sort((left, right) => left.path.localeCompare(right.path));
}

function readableLabel(segment: string) {
  const label = PACKAGE_LABELS[segment];
  if (label) {
    return label;
  }
  const words = segment
    .replace(/[-_]+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
  return {
    zh: words || segment,
    en: words || segment,
  };
}

function matchesPackage(item: LogPackageIndexItem, term: string) {
  const haystack = [
    item.titleZh,
    item.titleEn,
    item.path,
    ...item.files.flatMap((file) => [file.name, file.path]),
  ]
    .join("\n")
    .toLowerCase();
  return haystack.includes(term);
}

function filterPackage(item: LogPackageIndexItem, term: string): LogPackageIndexItem | null {
  if (!term) {
    return item;
  }
  const titleMatches =
    item.titleZh.toLowerCase().includes(term) ||
    item.titleEn.toLowerCase().includes(term) ||
    item.path.toLowerCase().includes(term);
  if (titleMatches) {
    return item;
  }
  const files = item.files.filter(
    (file) => file.name.toLowerCase().includes(term) || file.path.toLowerCase().includes(term),
  );
  if (files.length === 0 || !matchesPackage(item, term)) {
    return null;
  }
  return {
    ...item,
    fileCount: files.length,
    files,
  };
}

export function buildLogPackageIndex(nodes: FileTreeNode[], query = ""): LogPackageIndexItem[] {
  const packages: LogPackageIndexItem[] = [];
  const rootFiles: LogPackageFile[] = [];

  for (const node of nodes) {
    if (node.type === "file") {
      rootFiles.push({ name: node.name, path: node.path });
      continue;
    }
    const files = collectFiles(node.children ?? []);
    if (files.length === 0) {
      continue;
    }
    const label = readableLabel(node.name);
    packages.push({
      id: node.path,
      titleZh: label.zh,
      titleEn: label.en,
      path: node.path,
      fileCount: files.length,
      files,
    });
  }

  if (rootFiles.length > 0) {
    packages.unshift({
      id: ROOT_PACKAGE_ID,
      titleZh: "根目录日志",
      titleEn: "Root logs",
      path: "",
      fileCount: rootFiles.length,
      files: rootFiles.sort((left, right) => left.path.localeCompare(right.path)),
    });
  }

  const term = query.trim().toLowerCase();
  return packages
    .sort((left, right) => {
      if (left.id === ROOT_PACKAGE_ID) {
        return -1;
      }
      if (right.id === ROOT_PACKAGE_ID) {
        return 1;
      }
      return left.titleEn.localeCompare(right.titleEn);
    })
    .map((item) => filterPackage(item, term))
    .filter((item): item is LogPackageIndexItem => Boolean(item));
}

export function logPackageFilePaths(packages: LogPackageIndexItem[]) {
  return packages.flatMap((item) => item.files.map((file) => file.path));
}
