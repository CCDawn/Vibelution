import { Component, type ReactNode } from "react";

import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import styles from "./LazyConversationMarkdownRenderer.errorBoundary.styles";

type ConversationMarkdownErrorBoundaryProps = {
  content: string;
  classNames?: ConversationMarkdownClassNames;
  children: ReactNode;
};

type ConversationMarkdownErrorBoundaryState = {
  failed: boolean;
};

function markdownErrorNoteLang(): "zh" | "en" {
  if (typeof document === "undefined") {
    return "zh";
  }
  return document.documentElement.lang.startsWith("en") ? "en" : "zh";
}

/**
 * Module-internal guard for one conversation markdown block: a render crash
 * inside react-markdown must degrade to a readable raw-text fallback instead
 * of blanking the message stream. Shared by the lazy wrapper and the test sync
 * shim so both production and test paths get identical degradation.
 */
export class ConversationMarkdownErrorBoundary extends Component<
  ConversationMarkdownErrorBoundaryProps,
  ConversationMarkdownErrorBoundaryState
> {
  state: ConversationMarkdownErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): ConversationMarkdownErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    // Degrade quietly — the raw text stays readable on screen; only log enough
    // to diagnose a broken markdown payload without dumping unbounded content.
    console.warn(
      "[conversation-markdown-render-error]",
      error instanceof Error ? error.message : String(error),
    );
  }

  render() {
    if (!this.state.failed) {
      return this.props.children;
    }
    const text = String(this.props.content ?? "");
    if (!text.trim()) {
      return null;
    }
    const lang = markdownErrorNoteLang();
    const note = lang === "zh"
      ? "Markdown 渲染出错，已显示原文。"
      : "Markdown rendering failed; showing the raw text.";
    if (this.props.classNames?.markdownBody) {
      return (
        <div className={this.props.classNames.markdownBody} data-markdown-error-fallback="true">
          <p className={`${this.props.classNames.messageBody} ${styles.fallbackText}`}>
            {text}
          </p>
          <p className={styles.errorNote}>{note}</p>
        </div>
      );
    }
    return (
      <div className={styles.errorBox} data-markdown-error-fallback="true">
        <pre className={styles.fallbackPre}>{text}</pre>
        <p className={styles.errorNote}>{note}</p>
      </div>
    );
  }
}
