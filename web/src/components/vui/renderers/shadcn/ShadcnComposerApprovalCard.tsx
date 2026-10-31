import { Fragment, useId, type KeyboardEvent } from "react";
import { ShieldQuestion, X } from "lucide-react";
import { ShadcnButton } from "./ShadcnButton";

import type { VComposerApprovalCardProps } from "../../primitives/VComposerApprovalCard";

function isEditableTarget(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest("input, textarea, select, [contenteditable]:not([contenteditable='false'])"));
}

export function ShadcnComposerApprovalCard({
  lang, title, description, fullPreview, risk, scope, pending, approveDisabled, rejectDisabled, onApprove, onReject,
}: VComposerApprovalCardProps) {
  const titleId = useId();
  const zh = lang === "zh";
  const blockedApprove = pending || approveDisabled;
  const blockedReject = pending || rejectDisabled;
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey || event.repeat) return;
    if (isEditableTarget(event.target)) return;
    const key = event.key.toLowerCase();
    if (!["1", "2", "y", "n", "escape"].includes(key)) return;
    // Keep a simultaneously mounted legacy approval from consuming the same shortcut.
    event.preventDefault();
    event.stopPropagation();
    if ((key === "1" || key === "y") && !blockedApprove) onApprove();
    if ((key === "2" || key === "n" || key === "escape") && !blockedReject) onReject();
  };
  const optionClass = "!h-auto !min-h-11 !w-full !justify-start !gap-3 !rounded-xl !border-0 !bg-transparent !px-2 text-left !text-base font-medium text-[var(--fg-primary)] hover:!bg-vui-surface-row-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--fg-primary)] disabled:cursor-not-allowed disabled:opacity-45";
  return (
    <section role="dialog" aria-labelledby={titleId} aria-busy={pending} data-chat-tool-approval-variant="composer"
      className="flex max-h-[min(50vh,32rem)] min-h-0 w-full flex-col overflow-hidden rounded-[24px] border border-[var(--border-soft)] bg-vui-surface-card text-[var(--fg-primary)]"
      onKeyDown={onKeyDown}>
      <div className="flex shrink-0 items-center justify-between px-5 pt-4 text-sm text-[var(--fg-muted)] sm:px-6">
        <span className="flex items-center gap-2"><ShieldQuestion size={18} aria-hidden="true" />{zh ? "需要确认" : "Confirmation needed"}</span>
        <ShadcnButton variant="ghost" isIconOnly type="button" aria-label={zh ? "拒绝并关闭" : "Decline and close"} isDisabled={blockedReject} onClick={onReject}
          className="!size-11 !h-11 !min-h-11 !w-11 !rounded-lg !border-0 !bg-transparent !p-0 hover:!bg-vui-surface-row-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--fg-primary)] disabled:cursor-not-allowed disabled:opacity-45">
          <X size={18} aria-hidden="true" />
        </ShadcnButton>
      </div>
      <div data-approval-scroll-body className="min-h-0 overflow-y-auto px-5 pb-2 sm:px-6" tabIndex={0}>
        <h2 id={titleId} className="break-words text-xl font-semibold leading-snug">{title}</h2>
        {description ? <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-relaxed">{description}</p> : null}
        {risk || scope ? <p className="mt-3 text-sm text-[var(--fg-muted)]">{[risk, scope].filter(Boolean).join(" · ")}</p> : null}
        <details className="mt-3 text-sm text-[var(--fg-muted)]">
          <summary className="cursor-pointer rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--fg-primary)]">{zh ? "查看完整详情" : "View full details"}</summary>
          <div data-approval-full-preview tabIndex={0} className="mt-2 whitespace-pre-wrap [overflow-wrap:anywhere] text-[var(--fg-primary)]">{fullPreview.split("\n").map((line, index) => {
            const fact = line.match(/^((?:来源项目|来源实例|来源助理|原操作 ID|原同步 ID|当前来源快照摘要|原授权 head|项目|Agent|请求 ID|派遣 ID|任务 ID|审批 ID|轮次|调用|Source project|Source instance|Source assistant|Original operation ID|Original sync ID|Current source snapshot digest|Previous authorization head|Project|Request ID|Dispatch ID|Task ID|Approval ID|Turn|Call):\s*)(.*)$/);
            return <Fragment key={index}>{index ? "\n" : ""}{fact ? <>{fact[1]}<code className="font-mono">{fact[2]}</code></> : line}</Fragment>;
          })}</div>
        </details>
      </div>
      <div className="shrink-0 space-y-1 px-4 pb-4 pt-2 sm:px-5">
        <ShadcnButton variant="ghost" type="button" className={optionClass} isDisabled={blockedApprove} onClick={onApprove}>
          <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-md border border-[var(--border-soft)] text-sm">1</span>
          {pending ? (zh ? "处理中…" : "Resolving…") : (zh ? "允许本次" : "Allow once")}
        </ShadcnButton>
        <ShadcnButton variant="ghost" type="button" className={optionClass} isDisabled={blockedReject} onClick={onReject}>
          <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-md border border-[var(--border-soft)] text-sm">2</span>
          {zh ? "拒绝" : "Decline"}
        </ShadcnButton>
      </div>
    </section>
  );
}
