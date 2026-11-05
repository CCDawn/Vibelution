import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Info } from "lucide-react";
import { VButton, VSurface, VTextarea } from "../../components/vui";

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
      className="relative flex max-h-[min(72dvh,42rem)] w-full flex-col overflow-hidden !rounded-2xl border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-card)] shadow-xs">
      <form onSubmit={handleSubmit} aria-labelledby={`${id}-title`} data-launcher-assistant-question-form
        className="flex min-h-0 flex-1 flex-col gap-3 p-3">
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain pr-1">
          <h2 id={`${id}-title`} className="m-0 whitespace-pre-wrap break-words text-sm font-medium leading-6">{questionText}</h2>
          <div data-launcher-assistant-answer-row
            className={"flex w-full cursor-text items-center gap-3 rounded-xl px-3 py-2 transition-colors "
              + (value.trim() || rowFocused ? "bg-[var(--vui-control-muted)]" : "hover:bg-[var(--vui-control-muted)]")}
            onClick={() => { if (!inputDisabled) input.current?.focus(); }}>
            <span aria-hidden="true" className="mt-px w-5 shrink-0 self-start text-sm font-medium leading-5 text-[var(--fg-secondary)]">1.</span>
            <VTextarea ref={input} aria-label={zh ? "回答此问题" : "Answer this question"} value={value}
              onChange={event => { if (!inputDisabled) onChange(event.target.value); }}
              onFocus={() => setRowFocused(true)} onBlur={() => setRowFocused(false)}
              onKeyDown={handleKeyDown} disabled={inputDisabled} rows={1} wrap="soft"
              placeholder={zh ? "输入你的回答…" : "Type your answer…"}
              aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : `${id}-hint`}
              className="!h-auto !min-h-5 !max-h-[5lh] !min-w-0 !max-w-full !resize-none !overflow-y-auto !rounded-none !border-0 !bg-transparent !px-0 !py-0 !text-sm !font-medium !leading-5 !text-[var(--fg-primary)] ![box-shadow:none] [field-sizing:content] placeholder:!text-[var(--fg-tertiary)] focus:!bg-transparent focus:!outline-none focus:!ring-0 focus:!ring-offset-0" />
          </div>
          {error ? <p id={`${id}-error`} role="alert" className="m-0 px-1 text-[13px] text-[var(--vui-status-danger-fg)]">{error}</p> : null}
        </div>
        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 px-1">
          <p id={`${id}-hint`} className="m-0 flex min-w-0 flex-1 items-center gap-2 text-xs leading-5 text-[var(--fg-secondary)]">
            <Info size={14} aria-hidden="true" className="shrink-0" /><span>{hint}</span>
          </p>
          <VButton type="submit" isDisabled={submitDisabled} isPending={pending}
            className="!h-8 !min-h-8 !rounded-lg !border-[var(--fg-primary)] !bg-[var(--fg-primary)] !px-2.5 !text-sm !font-normal !text-[var(--vui-surface-card)] max-sm:!h-11 max-sm:!min-h-11">
            {submitLabel}
          </VButton>
        </footer>
      </form>
    </VSurface>
  );
}
