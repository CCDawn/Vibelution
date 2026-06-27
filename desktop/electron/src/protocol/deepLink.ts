export type VibelutionDeepLink =
  | { kind: "focus_launcher" }
  | { kind: "open_workbench"; path: string };

export type PublicVibelutionDeepLink = {
  kind: "focus_launcher";
  rawUrl: string;
};

export function parseVibelutionDeepLink(rawUrl: string): VibelutionDeepLink {
  const url = new URL(rawUrl);
  if (url.protocol !== "vibelution:") {
    throw new Error(`unsupported protocol: ${url.protocol}`);
  }
  const route = `${url.hostname}${url.pathname}`;
  if (route === "launcher/focus") {
    return { kind: "focus_launcher" };
  }
  if (route === "workbench/open") {
    const path = url.searchParams.get("path");
    if (!path) {
      throw new Error("missing workbench path");
    }
    return { kind: "open_workbench", path };
  }
  throw new Error(`unsupported deep link route: ${route}`);
}

export function parsePublicVibelutionDeepLink(rawUrl: string): PublicVibelutionDeepLink {
  const link = parseVibelutionDeepLink(rawUrl);
  if (link.kind !== "focus_launcher") {
    throw new Error(`deep link route is not public: ${link.kind}`);
  }
  return { ...link, rawUrl };
}

export function findVibelutionDeepLinkArg(argv: readonly string[]): string | null {
  for (const arg of argv) {
    if (isVibelutionDeepLinkUrl(arg)) {
      return arg;
    }
  }
  return null;
}

function isVibelutionDeepLinkUrl(value: string): boolean {
  try {
    return new URL(value).protocol === "vibelution:";
  } catch {
    return false;
  }
}
