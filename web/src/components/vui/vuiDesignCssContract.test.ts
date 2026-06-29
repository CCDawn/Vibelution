import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const designRoot = resolve(import.meta.dirname, "../../design");

function collectCssMatches(pattern: RegExp): string[] {
  return readdirSync(designRoot)
    .filter((name) => name.endsWith(".css") && name !== "tokens.css")
    .flatMap((name) => {
      const source = readFileSync(resolve(designRoot, name), "utf8");
      return [...source.matchAll(pattern)].map((match) => {
        const line = source.slice(0, match.index).split(/\r?\n/).length;
        return `${name}:${line}:${match[0]}`;
      });
    });
}

describe("VUI design CSS contract", () => {
  it("keeps raw color literals centralized in tokens.css", () => {
    expect(collectCssMatches(/#[0-9a-fA-F]{3,8}|rgba?\(/g)).toEqual([]);
  });

  it("keeps decorative gradients centralized in tokens.css", () => {
    expect(collectCssMatches(/linear-gradient\(/g)).toEqual([]);
  });
});
