import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  conversationToolDetailPresentation,
  type ConversationToolPresentationLanguage,
} from "./conversationToolPresentation";
import styles from "./ConversationTerminalToolDetail.styles";

export type ConversationTerminalToolDetailModel = {
  command: string;
  output: string;
  error: string;
};

type ConversationTerminalToolDetailProps = {
  detail: ConversationTerminalToolDetailModel;
  language: ConversationToolPresentationLanguage;
};

function firstNonEmptyText(...values: Array<string | undefined | null>) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function boundedTerminalDetailText(
  value: string,
  language: ConversationToolPresentationLanguage,
) {
  const normalized = value.trim();
  if (!normalized) {
    return "";
  }
  const maxLines = 18;
  const maxChars = 1600;
  const lines = normalized.split(/\r?\n/);
  const lineBounded = lines.slice(0, maxLines).join("\n").trimEnd();
  const lengthBounded = lineBounded.length > maxChars
    ? lineBounded.slice(0, maxChars).trimEnd()
    : lineBounded;
  const omittedLineCount = Math.max(0, lines.length - maxLines);
  const omittedCharCount = Math.max(0, normalized.length - lengthBounded.length);
  const notices = [
    omittedLineCount > 0
      ? (language === "zh" ? `已省略 ${omittedLineCount} 行` : `${omittedLineCount} lines omitted`)
      : "",
    omittedCharCount > 0
      ? (language === "zh" ? `已省略 ${omittedCharCount} 个字符` : `${omittedCharCount} characters omitted`)
      : "",
  ].filter(Boolean);
  return notices.length > 0
    ? `${lengthBounded}\n\n[${notices.join(language === "zh" ? "，" : ", ")}]`
    : lengthBounded;
}

function joinUniqueText(values: string[]) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].join("\n");
}

export function buildConversationTerminalToolDetail(
  cell: CodexTranscriptCell,
  language: ConversationToolPresentationLanguage,
): ConversationTerminalToolDetailModel | null {
  const model = cell.toolLifecycleModel;
  if (!model) {
    return null;
  }
  const operationIds = new Set(cell.operationIds ?? []);
  const matchedToolCalls = model.toolCalls.filter((toolCall) =>
    operationIds.size === 0
    || operationIds.has(toolCall.rawOperationId)
    || operationIds.has(toolCall.toolCallId)
    || (toolCall.terminalOperationId ? operationIds.has(toolCall.terminalOperationId) : false)
  );
  const toolCalls = (matchedToolCalls.length > 0 ? matchedToolCalls : model.toolCalls)
    .filter((toolCall) => toolCall.runtimeKind === "terminal");
  if (toolCalls.length === 0) {
    return null;
  }
  const toolCallIds = new Set(toolCalls.map((toolCall) => toolCall.toolCallId).filter(Boolean));
  const terminalOperations = model.terminalOperations.filter((operation) =>
    toolCallIds.has(operation.toolCallId)
    || operationIds.has(operation.rawOperationId)
    || operationIds.has(operation.operationId)
  );
  if (terminalOperations.length === 0) {
    return null;
  }

  const primaryToolCall = toolCalls[0];
  const toolName = primaryToolCall?.rawToolName || primaryToolCall?.title || cell.title;
  const present = (value: string) => boundedTerminalDetailText(
    conversationToolDetailPresentation({
      value,
      toolName,
      language,
    }),
    language,
  );
  const command = firstNonEmptyText(
    ...terminalOperations
      .filter((operation) => String(operation.kind).toLowerCase() !== "writestdin")
      .flatMap((operation) => [
        operation.request?.displayCommand,
        operation.request?.command?.join(" "),
      ]),
  );
  const outputs: string[] = [];
  const errors: string[] = [];
  for (const operation of terminalOperations) {
    const error = firstNonEmptyText(operation.result?.stderr);
    const output = firstNonEmptyText(
      operation.result?.formattedOutput,
      operation.result?.stdout,
    );
    if (output && output !== error) {
      outputs.push(output);
    }
    if (error) {
      errors.push(error);
    }
  }
  for (const toolCall of toolCalls) {
    if (toolCall.resultPreview) {
      outputs.push(toolCall.resultPreview);
    }
    if (toolCall.error) {
      errors.push(toolCall.error);
    }
  }

  const detail = {
    command: present(command),
    output: present(joinUniqueText(outputs)),
    error: present(joinUniqueText(errors)),
  };
  return detail.command || detail.output || detail.error ? detail : null;
}

export function ConversationTerminalToolDetail({
  detail,
  language,
}: ConversationTerminalToolDetailProps) {
  return (
    <section className={styles.root} data-codex-terminal-detail="true">
      <div className={styles.header}>Shell</div>
      {detail.command ? (
        <pre className={styles.command} aria-label={language === "zh" ? "命令" : "Command"} tabIndex={0}>
          {`$ ${detail.command}`}
        </pre>
      ) : null}
      {detail.output ? (
        <pre className={styles.output} aria-label={language === "zh" ? "输出" : "Output"} tabIndex={0}>
          {detail.output}
        </pre>
      ) : null}
      {detail.error ? (
        <pre className={styles.error} aria-label={language === "zh" ? "错误" : "Error"} tabIndex={0}>
          {detail.error}
        </pre>
      ) : null}
    </section>
  );
}
