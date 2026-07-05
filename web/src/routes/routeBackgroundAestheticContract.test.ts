import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const routeRoot = import.meta.dirname;

const BACKGROUND_AWARE_ROUTE_STYLE_FILES = [
  resolve(routeRoot, "LogsRoute.styles.ts"),
] as const;

function readSource(file: string) {
  return readFileSync(file, "utf-8");
}

function extractStyleValue(source: string, key: string) {
  const pattern = new RegExp(`${key}:\\s*\\r?\\n?\\s*"([^"]*)"`);
  return source.match(pattern)?.[1] ?? "";
}

describe("route background aesthetic contract", () => {
  it("keeps operational route roots from owning opaque surface-page wrappers", () => {
    const offenders = BACKGROUND_AWARE_ROUTE_STYLE_FILES.flatMap((file) => {
      const source = readSource(file);
      const routeValue = extractStyleValue(source, "route");

      return routeValue.includes("bg-[var(--surface-page)]")
        ? [`${file.split(/[/\\\\]/).pop()}:route`]
        : [];
    });

    expect(offenders).toEqual([]);
  });
});
