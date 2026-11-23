import type { BackendHealth } from "../api/types";

export type ServingBuildWarning = "" | "restart" | "fallback";

export type ServingBuildLabel = {
  /** Short release id; empty when this process pinned nothing. */
  release: string;
  /** Local HH:MM of the backend start; empty when unknown. */
  startedAt: string;
  /** Something about the served tree needs saying; never hide it. */
  warning: ServingBuildWarning;
  /** How the tree was chosen; empty when health has not answered yet. */
  source: string;
  /** One-line explanation for the title tooltip. */
  title: string;
};

const SHORT_RELEASE_LENGTH = 10;
const RELEASE_PREFIX = "release-";

/** `release-8fb7a9925ffad3e6` reads as `8fb7a9925f` in a dense top bar. */
export function shortReleaseId(release: string): string {
  const value = String(release || "").trim();
  if (!value) return "";
  const body = value.startsWith(RELEASE_PREFIX) ? value.slice(RELEASE_PREFIX.length) : value;
  return body.slice(0, SHORT_RELEASE_LENGTH);
}

/** Backend start as local HH:MM, so a page can say which process answered it. */
export function clockLabel(iso: string): string {
  const parsed = Date.parse(String(iso || "").trim());
  if (!Number.isFinite(parsed)) return "";
  const date = new Date(parsed);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/**
 * Turn a health payload into the identity line the top bar shows.
 *
 * Fails closed: an unknown payload renders nothing rather than claiming a
 * release. A stale pointer outranks a legacy fallback because a restart is the
 * action that fixes it, and the fallback is only worth naming when nothing
 * newer is waiting.
 */
export function describeServingBuild(
  health: BackendHealth | undefined,
  lang = "zh",
): ServingBuildLabel {
  const en = lang === "en";
  const release = shortReleaseId(String(health?.servingRelease || ""));
  const startedAt = clockLabel(String(health?.backendStartedAt || ""));
  const active = shortReleaseId(String(health?.activeRelease || ""));
  const source = String(health?.servingSource || "").trim();
  const fallbackReason = String(health?.servingFallbackReason || "").trim();
  const stale = Boolean(health?.releaseStale);
  const legacy = source === "legacy-dist";

  const warning: ServingBuildWarning = stale ? "restart" : legacy ? "fallback" : "";

  const parts = en
    ? [
        release ? `serving ${release}` : "",
        startedAt ? `backend up ${startedAt}` : "",
        stale && active ? `published ${active}; restart to serve it` : "",
        legacy ? `legacy tree${fallbackReason ? ` (${fallbackReason})` : ""}; no published release` : "",
      ]
    : [
        release ? `正在运行 ${release}` : "",
        startedAt ? `后端启动 ${startedAt}` : "",
        stale && active ? `已发布 ${active}，重启后生效` : "",
        legacy ? `旧产物回退${fallbackReason ? `（${fallbackReason}）` : ""}` : "",
      ];

  return {
    release,
    startedAt,
    warning,
    source,
    title: parts.filter(Boolean).join(" · "),
  };
}
