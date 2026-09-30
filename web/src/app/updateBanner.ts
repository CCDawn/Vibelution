import type { CodeFreshnessVerdict } from "../api/types";
import { shellDictionary } from "../i18n/shellDictionary";

/**
 * Workbench update banner (backend is behind disk HEAD): the running backend
 * keeps serving old code until the Launcher restarts the workbench, so the
 * shell surfaces a top banner with a restart action wired to the shared
 * lifecycle path. Dismissal stores the disk HEAD commit, so a NEW commit
 * re-prompts automatically without any extra bookkeeping.
 */
export const UPDATE_BANNER_DISMISSED_STORAGE_KEY = "vibelution.workbench.update-banner-dismissed.v1";

const UPDATE_BANNER_HEAD_TOKEN_LENGTH = 7;

/**
 * Only a stale BACKEND needs a restart to apply new code. A frontend-only
 * verdict keeps its existing coverage: the caution status dot plus the
 * "Refresh frontend" action in the settings popover.
 */
export function isUpdateBannerVerdict(verdict: CodeFreshnessVerdict | undefined | null): boolean {
  return verdict === "backend_behind" || verdict === "backend_and_frontend_behind";
}

export function shouldShowUpdateBanner({
  verdict,
  diskHead,
  dismissedHead,
}: {
  verdict: CodeFreshnessVerdict | undefined | null;
  diskHead: string | undefined | null;
  dismissedHead: string | undefined | null;
}): boolean {
  if (!isUpdateBannerVerdict(verdict)) {
    return false;
  }
  const head = String(diskHead ?? "").trim();
  if (!head) {
    return false;
  }
  return String(dismissedHead ?? "").trim() !== head;
}

/** Short commit token for copy, e.g. `@e91a851`. Empty when no HEAD is known. */
export function updateBannerHeadToken(diskHead: string | undefined | null): string {
  const head = String(diskHead ?? "").trim();
  if (!head) {
    return "";
  }
  return `@${head.slice(0, UPDATE_BANNER_HEAD_TOKEN_LENGTH)}`;
}

/**
 * Banner copy for the two distinct "behind" shapes:
 * - `commitsBehind > 0`: main moved ahead by real commits — the classic copy.
 * - `commitsBehind === null || 0` with a behind verdict: only the dirty-tree
 *   digest differs (uncommitted workspace changes), so the copy must speak
 *   about the working tree instead of a moved-ahead main.
 * A caller that cannot tell (argument omitted) keeps the moved-ahead framing.
 */
export function updateBannerCopy(
  lang: string,
  diskHead: string | undefined | null,
  frontendAlsoBehind: boolean,
  commitsBehind?: number | null,
): { title: string; detail: string } {
  if (commitsBehind !== undefined && (commitsBehind === null || commitsBehind <= 0)) {
    return updateBannerDirtyWorkspaceCopy(lang, frontendAlsoBehind);
  }
  const token = updateBannerHeadToken(diskHead);
  if (lang === "en") {
    return {
      title: "Code updated — restart to apply",
      detail: [
        token ? `main has moved ahead to ${token}.` : "main has moved ahead.",
        frontendAlsoBehind ? "The restart also loads the new frontend build." : "",
      ].filter(Boolean).join(" "),
    };
  }
  return {
    title: "代码已更新，重启后生效",
    detail: [
      token ? `main 已前进到 ${token}。` : "main 已前进。",
      frontendAlsoBehind ? "重启会同时加载新的前端构建。" : "",
    ].filter(Boolean).join(" "),
  };
}

function updateBannerDirtyWorkspaceCopy(
  lang: string,
  frontendAlsoBehind: boolean,
): { title: string; detail: string } {
  const pack = lang === "en" ? shellDictionary.en : shellDictionary.zh;
  return {
    title: pack.updateBannerDirtyTitle,
    detail: [
      pack.updateBannerDirtyDetail,
      frontendAlsoBehind ? (lang === "en" ? "The restart also loads the new frontend build." : "重启会同时加载新的前端构建。") : "",
    ].filter(Boolean).join(" "),
  };
}

export function updateBannerRestartLabel(lang: string): string {
  return lang === "en" ? "Restart now" : "立即重启";
}

export function updateBannerDismissLabel(lang: string): string {
  return lang === "en" ? "Dismiss until the next commit" : "下一个提交前不再提醒";
}

function updateBannerStorage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

export function readStoredUpdateBannerDismissedHead(): string {
  try {
    return String(updateBannerStorage()?.getItem(UPDATE_BANNER_DISMISSED_STORAGE_KEY) ?? "").trim();
  } catch {
    // Storage unavailable: treat as no dismissal for this visit.
    return "";
  }
}

export function storeUpdateBannerDismissedHead(head: string): void {
  try {
    updateBannerStorage()?.setItem(UPDATE_BANNER_DISMISSED_STORAGE_KEY, String(head ?? "").trim());
  } catch {
    // The in-memory dismissal state still covers this page visit.
  }
}
