import { useMemo } from "react";

import type { ConversationToolPresentationLanguage } from "./conversationToolPresentation";
import {
  buildConversationPatchDiff,
  type ConversationPatchFile,
  type ConversationPatchLine,
} from "./conversationPatchModel";
import styles from "./ConversationPatchDiff.styles";

type ConversationPatchDiffProps = {
  patchText: string;
  language: ConversationToolPresentationLanguage;
  /** Lines per file rendered before the rest folds behind a disclosure. */
  maxVisibleLinesPerFile?: number;
};

const DEFAULT_MAX_VISIBLE_LINES = 200;

function patchFileOpLabel(file: ConversationPatchFile, language: ConversationToolPresentationLanguage) {
  if (file.op === "add") {
    return language === "zh" ? "新增" : "Add";
  }
  if (file.op === "delete") {
    return language === "zh" ? "删除" : "Delete";
  }
  if (file.op === "update") {
    return language === "zh" ? "修改" : "Update";
  }
  return language === "zh" ? "补丁" : "Patch";
}

function patchLineStyle(line: ConversationPatchLine) {
  if (line.kind === "add") return styles.line_add;
  if (line.kind === "del") return styles.line_del;
  if (line.kind === "hunk") return styles.line_hunk;
  return styles.line_context;
}

function patchLineSign(line: ConversationPatchLine) {
  if (line.kind === "add") return "+";
  if (line.kind === "del") return "-";
  if (line.kind === "hunk") return "";
  return " ";
}

function patchLineSignStyle(line: ConversationPatchLine) {
  if (line.kind === "add") return styles.line_add_sign;
  if (line.kind === "del") return styles.line_del_sign;
  return "";
}

function PatchLine({ line }: { line: ConversationPatchLine }) {
  if (line.kind === "hunk") {
    return (
      <div className={`${styles.line} ${patchLineStyle(line)}`} data-patch-line-kind={line.kind}>
        <span aria-hidden="true" />
        <span className={styles.lineSign} aria-hidden="true" />
        <span className={styles.lineText}>{line.text}</span>
      </div>
    );
  }
  return (
    <div className={`${styles.line} ${patchLineStyle(line)}`} data-patch-line-kind={line.kind}>
      <span className={styles.lineNumber} aria-hidden="true">{line.oldLine ?? ""}</span>
      <span className={styles.lineNumber} aria-hidden="true">{line.newLine ?? ""}</span>
      <span className={styles.lineText}>
        <span className={`${styles.lineSign} ${patchLineSignStyle(line)}`} aria-hidden="true">
          {patchLineSign(line)}
        </span>
        {line.text}
      </span>
    </div>
  );
}

function PatchFileSection({
  file,
  language,
  maxVisibleLines,
}: {
  file: ConversationPatchFile;
  language: ConversationToolPresentationLanguage;
  maxVisibleLines: number;
}) {
  const visibleLines = file.lines.slice(0, maxVisibleLines);
  const overflowLines = file.lines.slice(maxVisibleLines);
  return (
    <section className={styles.file} data-codex-patch-file="true" data-patch-file-op={file.op}>
      <div className={styles.fileHeader}>
        <span className={styles.filePath} title={file.path || undefined}>
          {file.path || (language === "zh" ? "（未命名文件）" : "(unnamed file)")}
        </span>
        {file.moveTo ? (
          <span className={styles.fileMoveTo}>{`→ ${file.moveTo}`}</span>
        ) : null}
        <span className={styles.fileOp}>{patchFileOpLabel(file, language)}</span>
        <span className={styles.diffStat}>
          <span className={styles.diffStatAdd}>+{file.additions}</span>
          {" "}
          <span className={styles.diffStatDel}>−{file.deletions}</span>
        </span>
      </div>
      {visibleLines.length > 0 ? (
        <div className={styles.lines}>
          {visibleLines.map((line, index) => (
            <PatchLine key={`${file.path}-${index}`} line={line} />
          ))}
        </div>
      ) : null}
      {overflowLines.length > 0 ? (
        <details className={styles.overflow}>
          <summary className={styles.overflowSummary}>
            {language === "zh"
              ? `展开其余 ${overflowLines.length} 行`
              : `Show ${overflowLines.length} more lines`}
          </summary>
          <div className={styles.lines}>
            {overflowLines.map((line, index) => (
              <PatchLine key={`${file.path}-overflow-${index}`} line={line} />
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}

/**
 * Renders the canonical apply_patch payload of an edit tool call as an inline
 * code diff. Pure presentation: the patch text is already bounded upstream.
 */
export function ConversationPatchDiff({
  patchText,
  language,
  maxVisibleLinesPerFile = DEFAULT_MAX_VISIBLE_LINES,
}: ConversationPatchDiffProps) {
  const diff = useMemo(() => buildConversationPatchDiff(patchText), [patchText]);
  if (diff.files.length === 0) {
    return null;
  }
  const ariaLabel = language === "zh" ? "代码差异" : "Code diff";
  return (
    <div className={styles.root} data-codex-patch-diff="true" aria-label={ariaLabel}>
      {diff.files.map((file, index) => (
        <PatchFileSection
          key={`${file.path}-${file.op}-${index}`}
          file={file}
          language={language}
          maxVisibleLines={Math.max(1, maxVisibleLinesPerFile)}
        />
      ))}
      {diff.truncated ? (
        <p className={styles.truncated}>
          {language === "zh" ? "补丁内容过长，已截断显示。" : "Patch content was truncated."}
        </p>
      ) : null}
    </div>
  );
}

export default ConversationPatchDiff;
