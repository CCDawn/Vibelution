import { useState } from "react";
import { LoaderCircle, Play } from "lucide-react";

import { VNativeButton } from "../vui";
import {
  loadMermaidRenderer,
  nextMermaidRenderId,
  normalizeMermaidRenderError,
  resolveMermaidSourceBudgetDecision,
} from "./conversationMarkdownMermaid";
import styles from "./conversationMarkdownMermaidBlock.styles";

export type ConversationMarkdownMermaidBlockProps = {
  /** Raw fence source (trimmed by the caller). */
  code: string;
  /** Host-provided `responseSegmentPre` chrome for the plaintext states. */
  preClassName: string;
  language: "zh" | "en";
};

type MermaidBlockState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; svg: string }
  | { status: "failed"; message: string };

/**
 * Settled ```mermaid fence with an explicit render action (state machine:
 * idle → loading → ready(svg) / failed). Plaintext stays the resting state so
 * streaming and history render cheap; the mermaid module is imported only on
 * first render click. Sources over the budget (20k chars / 600 lines) never
 * enter the renderer — they show as plaintext with a hint instead of a button.
 * A failed render degrades back to plaintext with the parser error attached.
 */
export function ConversationMarkdownMermaidBlock({
  code,
  preClassName,
  language,
}: ConversationMarkdownMermaidBlockProps) {
  const zh = language === "zh";
  const trimmed = code.trim();
  const budget = resolveMermaidSourceBudgetDecision(trimmed);
  const [state, setState] = useState<MermaidBlockState>({ status: "idle" });

  const handleRender = () => {
    if (state.status === "loading") {
      return;
    }
    setState({ status: "loading" });
    void loadMermaidRenderer()
      .then((mermaid) => mermaid.render(nextMermaidRenderId(), trimmed))
      .then(({ svg }) => {
        setState({ status: "ready", svg });
      })
      .catch((error: unknown) => {
        setState({ status: "failed", message: normalizeMermaidRenderError(error) });
      });
  };

  const preClasses = [preClassName, styles.preAttached].filter(Boolean).join(" ");
  const overBudget = !budget.renderable;
  const overBudgetHint = !overBudget
    ? ""
    : budget.reason === "source-too-large"
      ? zh
        ? "图表过大（超过 20000 字符），仅显示源码"
        : "Diagram too large (over 20,000 chars) — showing source only"
      : zh
        ? "图表过大（超过 600 行），仅显示源码"
        : "Diagram too large (over 600 lines) — showing source only";
  const renderButtonLabel = zh ? "渲染 Mermaid 图表" : "Render Mermaid diagram";

  return (
    <div
      className={styles.shell}
      data-markdown-mermaid-block="true"
      data-mermaid-state={overBudget ? "over-budget" : state.status}
    >
      <div className={styles.codeBlock.header} data-markdown-code-block="true">
        <span className={styles.codeBlock.language}>mermaid</span>
        <span className={styles.codeBlock.actions}>
          {overBudget ? (
            <span className={styles.hint}>{overBudgetHint}</span>
          ) : state.status !== "loading" ? (
            <VNativeButton
              data-vui="icon-button"
              className={styles.codeBlock.headerButton}
              onClick={handleRender}
              aria-label={renderButtonLabel}
              title={zh ? "渲染图表" : "Render diagram"}
            >
              <Play size={14} aria-hidden="true" />
            </VNativeButton>
          ) : null}
        </span>
      </div>
      {state.status === "ready" ? (
        <div
          className={styles.canvas}
          role="img"
          aria-label={zh ? "Mermaid 图表" : "Mermaid diagram"}
          dangerouslySetInnerHTML={{ __html: state.svg }}
        />
      ) : (
        <>
          {state.status === "loading" || state.status === "failed" ? (
            <div className={styles.status} role={state.status === "loading" ? "status" : undefined}>
              {state.status === "loading" ? (
                <>
                  <LoaderCircle size={12} aria-hidden="true" className={styles.statusSpinner} />
                  <span>{zh ? "正在渲染…" : "Rendering…"}</span>
                </>
              ) : (
                <span className={styles.hint}>
                  {zh ? "Mermaid 渲染失败，已显示源码" : "Mermaid render failed — showing source"}
                  {state.message ? `：${state.message}` : ""}
                </span>
              )}
            </div>
          ) : null}
          <pre className={preClasses}>{trimmed}</pre>
        </>
      )}
    </div>
  );
}
