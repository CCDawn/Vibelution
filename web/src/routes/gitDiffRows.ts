export type GitDiffLineTone = "added" | "removed" | "context" | "hunk" | "meta" | "section" | "empty";

export type GitDiffRow = {
  id: string;
  tone: GitDiffLineTone;
  marker: string;
  text: string;
  oldLine: number | null;
  newLine: number | null;
};

type BuildGitDiffRowsInput = {
  diff?: string;
  content?: string;
  binary?: boolean;
  loading?: boolean;
  loadingText: string;
  binaryText: string;
  emptyText: string;
};

const HUNK_HEADER_RE = /^@@ -(?<oldStart>\d+)(?:,\d+)? \+(?<newStart>\d+)(?:,\d+)? @@/;

export function buildGitDiffRows({
  diff = "",
  content = "",
  binary = false,
  loading = false,
  loadingText,
  binaryText,
  emptyText,
}: BuildGitDiffRowsInput): GitDiffRow[] {
  if (loading) {
    return [plainRow("loading", loadingText, "empty")];
  }
  if (binary) {
    return [plainRow("binary", binaryText, "meta")];
  }
  const diffText = diff.trimEnd();
  if (diffText) {
    return parseUnifiedDiff(diffText);
  }
  const contentText = content.trimEnd();
  if (contentText) {
    return parseUntrackedContent(contentText);
  }
  return [plainRow("empty", emptyText, "empty")];
}

function parseUnifiedDiff(value: string): GitDiffRow[] {
  let oldLine: number | null = null;
  let newLine: number | null = null;

  return splitLines(value).map((line, index) => {
    const id = `diff-${index}`;
    const hunkMatch = HUNK_HEADER_RE.exec(line);
    if (hunkMatch?.groups) {
      oldLine = Number(hunkMatch.groups.oldStart);
      newLine = Number(hunkMatch.groups.newStart);
      return { id, tone: "hunk", marker: "@@", text: line, oldLine: null, newLine: null };
    }

    if (line.startsWith("# ")) {
      return { id, tone: "section", marker: "", text: line.slice(2), oldLine: null, newLine: null };
    }
    if (isDiffMetadataLine(line)) {
      return { id, tone: "meta", marker: "", text: line, oldLine: null, newLine: null };
    }
    if (line.startsWith("+")) {
      const row = { id, tone: "added" as const, marker: "+", text: line.slice(1), oldLine: null, newLine };
      if (newLine !== null) {
        newLine += 1;
      }
      return row;
    }
    if (line.startsWith("-")) {
      const row = { id, tone: "removed" as const, marker: "-", text: line.slice(1), oldLine, newLine: null };
      if (oldLine !== null) {
        oldLine += 1;
      }
      return row;
    }
    if (line.startsWith(" ")) {
      const row = {
        id,
        tone: "context" as const,
        marker: "",
        text: line.slice(1),
        oldLine,
        newLine,
      };
      if (oldLine !== null) {
        oldLine += 1;
      }
      if (newLine !== null) {
        newLine += 1;
      }
      return row;
    }
    return { id, tone: "meta" as const, marker: "", text: line, oldLine: null, newLine: null };
  });
}

function parseUntrackedContent(value: string): GitDiffRow[] {
  return splitLines(value).map((line, index) => ({
    id: `content-${index}`,
    tone: "added",
    marker: "+",
    text: line,
    oldLine: null,
    newLine: index + 1,
  }));
}

function plainRow(id: string, text: string, tone: GitDiffLineTone): GitDiffRow {
  return {
    id,
    tone,
    marker: "",
    text,
    oldLine: null,
    newLine: null,
  };
}

function splitLines(value: string): string[] {
  return value.split(/\r?\n/);
}

function isDiffMetadataLine(line: string): boolean {
  return (
    line.startsWith("diff --git ") ||
    line.startsWith("index ") ||
    line.startsWith("--- ") ||
    line.startsWith("+++ ") ||
    line.startsWith("new file mode ") ||
    line.startsWith("deleted file mode ") ||
    line.startsWith("old mode ") ||
    line.startsWith("new mode ") ||
    line.startsWith("rename from ") ||
    line.startsWith("rename to ") ||
    line.startsWith("similarity index ") ||
    line.startsWith("dissimilarity index ") ||
    line.startsWith("Binary files ") ||
    line.startsWith("\\ No newline at end of file")
  );
}
