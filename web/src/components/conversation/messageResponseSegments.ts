export type ResponseSegmentKind =
  | "answer"
  | "status"
  | "commit"
  | "verification"
  | "code"
  | "files"
  | "logs";

export type ResponseSegment = {
  id: string;
  kind: ResponseSegmentKind;
  content: string;
  language?: string;
};

type TextBlock = {
  type: "text";
  content: string;
};

type CodeBlock = {
  type: "code";
  content: string;
  language: string;
};

type ParsedBlock = TextBlock | CodeBlock;

const COMMIT_HASH_RE = /\b[0-9a-f]{7,40}\b/i;
const FILE_PATH_RE = /(?:^|\s)(?:[A-Za-z]:\\|\.{0,2}\/|[\w.-]+\/)[\w./\\ -]+\.[A-Za-z0-9]{1,8}(?=\s|$|[,:;。)、])/;
const EVENT_CODE_RE = /\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\b/i;

export function parseResponseSegments(content: string): ResponseSegment[] {
  const blocks = parseBlocks(content);
  const segments: ResponseSegment[] = [];
  let pendingKind: ResponseSegmentKind | null = null;

  for (const block of blocks) {
    if (block.type === "text") {
      const labelKind = classifyStandaloneLabel(block.content);
      if (labelKind) {
        pendingKind = labelKind;
        continue;
      }
      const kind = pendingKind ?? classifyTextBlock(block.content);
      segments.push({
        id: `segment-${segments.length}`,
        kind,
        content: block.content,
      });
      pendingKind = null;
      continue;
    }

    const kind = pendingKind === "commit" || pendingKind === "verification" || pendingKind === "files" || pendingKind === "logs"
      ? pendingKind
      : "code";
    segments.push({
      id: `segment-${segments.length}`,
      kind,
      content: block.content,
      language: block.language,
    });
    pendingKind = null;
  }

  return segments;
}

function parseBlocks(content: string): ParsedBlock[] {
  const normalized = String(content ?? "").replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const blocks: ParsedBlock[] = [];
  let textLines: string[] = [];

  function flushText() {
    const text = textLines.join("\n").trim();
    if (text) {
      blocks.push({ type: "text", content: text });
    }
    textLines = [];
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fence = line.match(/^\s*```([A-Za-z0-9_+.-]*)\s*$/);
    if (!fence) {
      if (line.trim() === "") {
        flushText();
      } else {
        textLines.push(line);
      }
      continue;
    }

    flushText();
    const codeLines: string[] = [];
    const language = fence[1]?.trim() || "text";
    index += 1;
    for (; index < lines.length; index += 1) {
      if (/^\s*```\s*$/.test(lines[index])) {
        break;
      }
      codeLines.push(lines[index]);
    }
    blocks.push({
      type: "code",
      content: codeLines.join("\n"),
      language,
    });
  }

  flushText();
  return blocks;
}

function classifyStandaloneLabel(content: string): ResponseSegmentKind | null {
  const normalized = normalizeLabel(content);
  if (!normalized || normalized.length > 18) {
    return null;
  }
  if (["已提交", "提交", "commit", "committed"].includes(normalized)) {
    return "commit";
  }
  if (["验证", "验证已跑", "测试", "tests", "verification"].includes(normalized)) {
    return "verification";
  }
  if (["改动文件", "文件", "files", "changed files"].includes(normalized)) {
    return "files";
  }
  if (["日志", "运行日志", "logs", "telemetry"].includes(normalized)) {
    return "logs";
  }
  return null;
}

function classifyTextBlock(content: string): ResponseSegmentKind {
  const normalized = content.trim();
  const lower = normalized.toLowerCase();

  if (looksLikeCommit(normalized)) {
    return "commit";
  }
  if (looksLikeVerification(normalized)) {
    return "verification";
  }
  if (looksLikeFileList(normalized)) {
    return "files";
  }
  if (looksLikeLogOrSignal(normalized)) {
    return "logs";
  }
  if (looksLikeStatus(normalized)) {
    return "status";
  }
  if (lower.startsWith("error:") || lower.startsWith("warning:")) {
    return "logs";
  }
  return "answer";
}

function normalizeLabel(content: string) {
  return content
    .trim()
    .replace(/^#+\s*/, "")
    .replace(/[：:。.\s]+$/g, "")
    .trim()
    .toLowerCase();
}

function looksLikeCommit(content: string) {
  const lower = content.toLowerCase();
  return (
    COMMIT_HASH_RE.test(content)
    && (
      /\b(fix|feat|docs|test|refactor|chore|style|perf|build|ci)(\(.+\))?:/.test(lower)
      || lower.includes("commit")
      || lower.includes("提交")
    )
  );
}

function looksLikeVerification(content: string) {
  const lower = content.toLowerCase();
  return (
    /\b\d+\s+passed\b/.test(lower)
    || /\b\d+\s+failed\b/.test(lower)
    || /\bpytest\b/.test(lower)
    || /\bvitest\b/.test(lower)
    || /\bnpm test\b/.test(lower)
    || lower.includes("验证通过")
    || lower.includes("测试通过")
    || lower.includes("验证已跑")
  );
}

function looksLikeFileList(content: string) {
  const lines = content.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length >= 2 && lines.every((line) => /^[-*]\s+/.test(line) && FILE_PATH_RE.test(line))) {
    return true;
  }
  return FILE_PATH_RE.test(content) && /文件|改动|changed|modified|新增|删除/.test(content);
}

function looksLikeLogOrSignal(content: string) {
  const lower = content.toLowerCase();
  return (
    EVENT_CODE_RE.test(content)
    || lower.includes("log")
    || lower.includes("telemetry")
    || lower.includes("runtime scene")
    || lower.includes("provider_protocol_error")
    || lower.includes("trace")
    || lower.includes("日志")
    || lower.includes("信号")
  );
}

function looksLikeStatus(content: string) {
  const normalized = content.trim();
  const lineCount = normalized.split("\n").filter(Boolean).length;
  if (lineCount > 2 || normalized.length > 120) {
    return false;
  }
  return /^(已|正在|开始|继续|完成|提交已|修复已|验证已|本轮已|current|done|completed|running|started)/i.test(normalized);
}
