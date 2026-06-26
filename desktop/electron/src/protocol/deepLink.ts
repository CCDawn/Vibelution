export type VibelutionDeepLink =
  | { kind: "focus_launcher" }
  | { kind: "open_workbench"; path: string };

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
