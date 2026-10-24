import { useEffect } from "react";
import { recordChatStartupMilestone } from "../../app/chatStartupMetrics";

function visible(element: HTMLElement | null): element is HTMLElement {
  if (!element?.isConnected || document.visibilityState !== "visible"
    || element.closest("[hidden], [inert], [aria-hidden='true']")) return false;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0 || rect.bottom <= 0 || rect.right <= 0
    || rect.top >= window.innerHeight || rect.left >= window.innerWidth) return false;
  let left = Math.max(0, rect.left), right = Math.min(window.innerWidth, rect.right);
  let top = Math.max(0, rect.top), bottom = Math.min(window.innerHeight, rect.bottom);
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse"
      || style.opacity === "0") return false;
    if (node !== element) {
      const parentRect = node.getBoundingClientRect();
      if (/(auto|scroll|hidden|clip)/.test(style.overflowX || style.overflow)) {
        left = Math.max(left, parentRect.left); right = Math.min(right, parentRect.right);
      }
      if (/(auto|scroll|hidden|clip)/.test(style.overflowY || style.overflow)) {
        top = Math.max(top, parentRect.top); bottom = Math.min(bottom, parentRect.bottom);
      }
    }
  }
  return right > left && bottom > top;
}

type Candidate = { transcript: HTMLElement | null; input: HTMLTextAreaElement | null };

/** Observe the real lazy-mounted native surface without mounting or focusing it. */
export function useChatStartupPresentation({
  sessionId, enabled, transcriptPending,
}: { sessionId: string; enabled: boolean; transcriptPending: boolean }) {
  useEffect(() => {
    if (!enabled || !sessionId || transcriptPending) return;
    let frame = 0;
    let transcriptReported = false;
    let composerReported = false;
    let stopped = false;
    const stop = () => {
      stopped = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener("visibilitychange", schedule);
      window.removeEventListener("resize", schedule);
    };
    const candidate = (): Candidate => {
      const empty = { transcript: null, input: null };
      if (stopped || document.visibilityState !== "visible") return empty;
      // Existing AgentThread identity distinguishes native session surfaces;
      // never accept an unrelated textarea elsewhere in the workbench.
      const surface = [...document.querySelectorAll<HTMLElement>("[data-agent-thread-id]")]
        .find((node) => node.dataset.agentThreadId === sessionId);
      if (!surface || !visible(surface)
        || surface.querySelector("[data-testid='conversation-transcript-loading-state']")) return empty;
      const timeline = surface.querySelector<HTMLElement>("[data-conversation-following]");
      const transcript = timeline
        ? [...timeline.querySelectorAll<HTMLElement>("[data-conversation-row-key], [data-vui='state-surface'][data-tone='empty']")]
          .find(visible) ?? null
        : null;
      const input = surface.querySelector<HTMLTextAreaElement>("textarea:not([data-conversation-inline-edit-input])");
      if (visible(input) && !input.disabled && !input.readOnly
        && !input.closest("[aria-disabled='true']")) {
        const rect = input.getBoundingClientRect();
        const hit = document.elementFromPoint(
          (Math.max(0, rect.left) + Math.min(window.innerWidth, rect.right)) / 2,
          (Math.max(0, rect.top) + Math.min(window.innerHeight, rect.bottom)) / 2,
        );
        if (hit === input) return { transcript, input };
      }
      return { transcript, input: null };
    };
    const inspect = (before: Candidate) => {
      frame = 0;
      const after = candidate();
      if (!transcriptReported && after.transcript && after.transcript === before.transcript) {
        recordChatStartupMilestone(sessionId, "transcriptPresented");
        transcriptReported = true;
      }
      if (!composerReported && after.input && after.input === before.input) {
        recordChatStartupMilestone(sessionId, "composerReady");
        composerReported = true;
      }
      if (transcriptReported && composerReported) stop();
      else if ((!transcriptReported && after.transcript) || (!composerReported && after.input)) schedule();
    };
    function schedule() {
      if (stopped || frame) return;
      // The second callback runs after a rendering opportunity for the commit.
      // This is a DOM presentation milestone, not proof of GPU pixel delivery.
      frame = requestAnimationFrame(() => {
        const before = candidate();
        frame = requestAnimationFrame(() => inspect(before));
      });
    }
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, {
      subtree: true, childList: true, attributes: true,
      attributeFilter: ["disabled", "readonly", "hidden", "inert", "aria-hidden", "class", "style", "data-agent-thread-id"],
    });
    document.addEventListener("visibilitychange", schedule);
    window.addEventListener("resize", schedule);
    schedule();
    return stop;
  }, [enabled, sessionId, transcriptPending]);
}
