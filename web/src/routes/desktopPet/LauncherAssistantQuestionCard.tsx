import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Info } from "lucide-react";
import { VButton, VSurface, VTextarea } from "../../components/vui";
import styles from "./LauncherAssistantQuestionCard.styles";

export type LauncherAssistantQuestionCardProps = {
  questionId: string;
  questionText: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  pending?: boolean;
  disabled?: boolean;
  unconfirmed?: boolean;
  error?: string;
  lang: "zh" | "en";
};

/** Approved ZCode ElicitationDialog composition; submission stays with the route. */
export function LauncherAssistantQuestionCard({
  questionId,
  questionText,
  value,
  onChange,
  onSubmit,
  pending = false,
  disabled = false,
  unconfirmed = false,
  error,
  lang,
}: LauncherAssistantQuestionCardProps) {
  const id = useId();
  const input = useRef<HTMLTextAreaElement>(null);
  const [rowFocused, setRowFocused] = useState(false);
  const inputDisabled = disabled || pending || unconfirmed;
  const submitDisabled = disabled || pending || (!unconfirmed && !value.trim());
  const zh = lang === "zh";
  const hint = pending
    ? (zh ? "正在提交…" : "Submitting…")
    : (zh ? "Enter 提交 · Shift + Enter 换行" : "Enter to submit · Shift + Enter for a new line");
  const submitLabel = pending
    ? (zh ? "提交中" : "Submitting")
    : unconfirmed || error
      ? (zh ? "重试" : "Retry")
      : (zh ? "提交" : "Submit");

  function submit() {
    if (!submitDisabled) onSubmit();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (inputDisabled || event.key !== "Enter" || event.shiftKey
      || event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    submit();
  }

  return (
    <VSurface tone="card" elevation="flat" padding="none" ariaLabel={zh ? "回答问题" : "Answer question"}
      data-launcher-assistant-pending-question={questionId}
      className={styles.card}>
      <form onSubmit={handleSubmit} aria-labelledby={`${id}-title`} data-launcher-assistant-question-form
        className={styles.form}>
        <div className={styles.body}>
          <h2 id={`${id}-title`} className={styles.title}>{questionText}</h2>
          <div data-launcher-assistant-answer-row
            className={`${styles.answerRow} ${value.trim() || rowFocused ? styles.selectedRow : styles.idleRow}`}
            onClick={() => { if (!inputDisabled) input.current?.focus(); }}>
            <span aria-hidden="true" className={styles.number}>1.</span>
            <VTextarea ref={input} aria-label={zh ? "回答此问题" : "Answer this question"} value={value}
              onChange={event => { if (!inputDisabled) onChange(event.target.value); }}
              onFocus={() => setRowFocused(true)} onBlur={() => setRowFocused(false)}
              onKeyDown={handleKeyDown} disabled={inputDisabled} rows={1} wrap="soft"
              placeholder={zh ? "输入你的回答…" : "Type your answer…"}
              aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : `${id}-hint`}
              className={styles.input} />
          </div>
          {error ? <p id={`${id}-error`} role="alert" className={styles.error}>{error}</p> : null}
        </div>
        <footer className={styles.footer}>
          <p id={`${id}-hint`} className={styles.hint}>
            <Info size={14} aria-hidden="true" className={styles.icon} /><span>{hint}</span>
          </p>
          <VButton type="submit" isDisabled={submitDisabled} isPending={pending}
            className={styles.submit}>
            {submitLabel}
          </VButton>
        </footer>
      </form>
    </VSurface>
  );
}
