import type { CodeFreshnessVerdict, LauncherFreshness } from "../api/types";
import { shellDictionary } from "../i18n/shellDictionary";

/**
 * Workbench update banner: include frontend and Launcher versions so a
 * current backend cannot hide a stale interface or desktop shell.
 * Dismissal stores the disk HEAD commit; a new commit prompts again.
 */
export const UPDATE_BANNER_DISMISSED_STORAGE_KEY = "vibelution.workbench.update-banner-dismissed.v1";

const UPDATE_BANNER_HEAD_TOKEN_LENGTH = 7;

export function isUpdateBannerVerdict(verdict: CodeFreshnessVerdict | undefined | null): boolean {
  return verdict === "backend_behind" || verdict === "backend_and_frontend_behind" || verdict === "frontend_behind";
}

export function isLauncherUpdateAvailable(freshness: LauncherFreshness | undefined | null): boolean {
  return Boolean(freshness && (freshness.current === false || freshness.shellStale || freshness.updateAvailable));
}

export function shouldShowUpdateBanner({
  verdict,
  diskHead,
  dismissedHead,
  launcherFreshness,
}: {
  verdict: CodeFreshnessVerdict | undefined | null;
  diskHead: string | undefined | null;
  dismissedHead: string | undefined | null;
  launcherFreshness?: LauncherFreshness | null;
}): boolean {
  if (!isUpdateBannerVerdict(verdict) && !isLauncherUpdateAvailable(launcherFreshness)) {
    return false;
  }
  const head = String(diskHead ?? "").trim();
  if (!head) {
    return false;
  }
  return String(dismissedHead ?? "").trim() !== head;
}

export function launcherUpdateBannerCopy(lang: string): { title: string; detail: string } {
  return lang === "en"
    ? { title: "Launcher update available", detail: "Launcher is running an earlier version. Open Launcher to update and restart." }
    : { title: "启动器有更新", detail: "启动器仍在运行较早版本，请打开启动管理更新并重启。" };
}

export function frontendUpdateBannerCopy(lang: string): { title: string; detail: string } {
  return lang === "en"
    ? { title: "Frontend updated — restart to apply", detail: "The interface build is behind local code. Restart to load the latest frontend." }
    : { title: "前端有更新，重启后生效", detail: "运行中的界面构建落后于本地代码，重启会加载最新前端。" };
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

/**
 * An accepted update-banner restart publishes the current frontend release
 * and replaces the backend, but the open window stays on the old document
 * until something reloads it. Rejected requests and `restart_queued` do not
 * complete that replacement, so this page must stay where it is.
 */
export function updateBannerRestartReloadsDocument(
  code: string | null | undefined,
  accepted?: boolean | null,
): boolean {
  if (accepted === false) {
    return false;
  }
  return String(code ?? "").trim() !== "restart_queued";
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
