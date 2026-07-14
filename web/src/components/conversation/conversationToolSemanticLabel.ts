export type ConversationToolSemanticLabelInput = {
  toolName?: string;
  summary?: string;
  commandSource?: unknown;
};

const CLI_TOOL_LABELS = {
  gitStatus: "检查 Git 状态",
  gitChanges: "查看 Git 变更",
  gitCommit: "提交变更",
  test: "运行测试",
  build: "构建项目",
  search: "搜索代码",
  read: "读取文件",
  fallback: "执行命令",
} as const;

const FRIENDLY_TOOL_LABELS: Record<string, string> = {
  grep_search_tool: "搜索",
  read_file_tool: "读取文件",
  glob_tool: "列出文件",
  code_symbol_tool: "代码图谱",
  search_code_tool: "搜索代码",
  get_git_status_summary_tool: "Git 状态",
  image2_generate_tool: "生成图片",
  web_search_tool: "网页搜索",
  web_fetch_tool: "网页读取",
  computer_use_task_tool: "沙盒浏览器",
  task_list_tool: "任务列表",
  task_create_tool: "创建任务",
  task_update_tool: "更新任务",
  source_collection_context_tool: "读取资料上下文",
  source_collection_stage_writeback_tool: "资料提炼回写",
  rg: "搜索",
};

export function conversationToolSemanticLabel(
  input: ConversationToolSemanticLabelInput,
): string {
  const normalizedName = String(input.toolName ?? "").trim();
  const lowerName = normalizedName.toLowerCase();
  if (lowerName === "cli_tool") {
    return cliToolSemanticLabel(input.summary, input.commandSource);
  }
  if (!normalizedName) {
    return "tool";
  }
  if (FRIENDLY_TOOL_LABELS[lowerName]) {
    return FRIENDLY_TOOL_LABELS[lowerName];
  }
  if (lowerName.includes("search")) {
    return "搜索";
  }
  if (lowerName.includes("read") || lowerName.includes("file")) {
    return "读取";
  }
  if (lowerName.includes("git")) {
    return "Git";
  }
  if (lowerName.includes("image")) {
    return "图片";
  }
  return normalizedName;
}

function cliToolSemanticLabel(summary: string | undefined, commandSource: unknown): string {
  const command = [String(summary ?? ""), collectCommandSource(commandSource)]
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();

  if (/\bgit(?:\.exe)?\s+(?:-[^\s]+\s+)*status\b/.test(command)) {
    return CLI_TOOL_LABELS.gitStatus;
  }
  if (/\bgit(?:\.exe)?\s+(?:-[^\s]+\s+)*(?:diff|show)\b/.test(command)) {
    return CLI_TOOL_LABELS.gitChanges;
  }
  if (/\bgit(?:\.exe)?\s+(?:-[^\s]+\s+)*commit\b/.test(command)) {
    return CLI_TOOL_LABELS.gitCommit;
  }
  if (
    /\b(?:vitest|pytest|jest)\b/.test(command)
    || /\b(?:npm|pnpm|yarn|bun)\b[^\r\n]{0,160}\b(?:run\s+)?test(?::[\w-]+)?\b/.test(command)
  ) {
    return CLI_TOOL_LABELS.test;
  }
  if (/\b(?:npm|pnpm|yarn|bun)\b[^\r\n]{0,160}\b(?:run\s+)?build\b/.test(command)) {
    return CLI_TOOL_LABELS.build;
  }
  if (/(?:^|[\s;&|])(?:rg|grep|ripgrep|select-string)(?:\.exe)?(?:\s|$)/.test(command)) {
    return CLI_TOOL_LABELS.search;
  }
  if (/(?:^|[\s;&|])(?:get-content|cat|type)(?:\.exe)?(?:\s|$)/.test(command)) {
    return CLI_TOOL_LABELS.read;
  }
  return CLI_TOOL_LABELS.fallback;
}

function collectCommandSource(value: unknown, depth = 0): string {
  if (depth > 3 || value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => collectCommandSource(item, depth + 1)).filter(Boolean).join(" ");
  }
  if (typeof value !== "object") {
    return "";
  }
  return Object.entries(value as Record<string, unknown>)
    .filter(([key]) => /^(?:command|cmd|script|argv|displayCommand)$/i.test(key))
    .map(([, item]) => collectCommandSource(item, depth + 1))
    .filter(Boolean)
    .join(" ");
}
