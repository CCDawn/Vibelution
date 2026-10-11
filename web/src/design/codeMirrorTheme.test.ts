import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { tags } from "@lezer/highlight";
import {
  workbenchCodeMirrorSyntaxHighlightStyle,
  workbenchCodeMirrorTheme,
} from "./codeMirrorTheme";

type Rgb = readonly [number, number, number];

const tokenSource = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");
const lightThemeStart = tokenSource.indexOf('[data-theme="light"]');
const themeBlocks = {
  dark: tokenSource.slice(0, lightThemeStart),
  light: tokenSource.slice(lightThemeStart),
} as const;

function getTokenValue(theme: string, token: string): string {
  const declaration = theme.match(new RegExp(`${token}:\\s*([^;]+);`))?.[1];
  if (!declaration) throw new Error(`Missing design token ${token}`);
  return declaration.trim();
}

function parseRgb(value: string): Rgb {
  const hex = value.match(/^#([\da-f]{6})$/i)?.[1];
  if (hex) {
    return [0, 2, 4].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16)) as unknown as Rgb;
  }

  const rgb = value.match(/^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)$/i);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  throw new Error(`Unsupported test color value: ${value}`);
}

function resolveColor(theme: string, value: string, depth = 0): Rgb {
  if (depth > 6) throw new Error(`Circular design token reference: ${value}`);

  const variable = value.match(/^var\((--[\w-]+)\)$/);
  if (variable) return resolveColor(theme, getTokenValue(theme, variable[1]), depth + 1);

  const mix = value.match(
    /^color-mix\(in srgb,\s*var\((--[\w-]+)\)\s+([\d.]+)%,\s*var\((--[\w-]+)\)\s+([\d.]+)%\)$/i,
  );
  if (mix) {
    const first = resolveColor(theme, getTokenValue(theme, mix[1]), depth + 1);
    const second = resolveColor(theme, getTokenValue(theme, mix[3]), depth + 1);
    const firstWeight = Number(mix[2]) / 100;
    const secondWeight = Number(mix[4]) / 100;
    return first.map((channel, index) => channel * firstWeight + second[index] * secondWeight) as unknown as Rgb;
  }

  return parseRgb(value);
}

function relativeLuminance([red, green, blue]: Rgb): number {
  const linear = (channel: number) => {
    const normalized = channel / 255;
    return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue);
}

function contrastRatio(first: Rgb, second: Rgb): number {
  const firstLuminance = relativeLuminance(first);
  const secondLuminance = relativeLuminance(second);
  return (Math.max(firstLuminance, secondLuminance) + 0.05)
    / (Math.min(firstLuminance, secondLuminance) + 0.05);
}

function styleFor(tag: unknown): Record<string, unknown> | undefined {
  return workbenchCodeMirrorSyntaxHighlightStyle.specs.find((spec) => {
    const specTags = Array.isArray(spec.tag) ? spec.tag : [spec.tag];
    return specTags.includes(tag as never);
  });
}

describe("workbench CodeMirror syntax theme", () => {
  it("adds adaptive token highlighting without replacing editor selection and focus styles", () => {
    expect(workbenchCodeMirrorTheme).toHaveLength(2);
    expect(styleFor(tags.comment)?.color).toBe("var(--fg-secondary)");
    expect(styleFor(tags.string)?.color).toBe(
      "color-mix(in srgb, var(--state-success) 78%, var(--fg-primary) 22%)",
    );
    expect(styleFor(tags.keyword)?.color).toBe("var(--accent-cool-2)");
  });

  it("keeps every colored syntax category readable on dark, light, and active-line surfaces", () => {
    const coloredStyles = workbenchCodeMirrorSyntaxHighlightStyle.specs
      .map((spec) => spec.color)
      .filter((color): color is string => typeof color === "string");

    expect(coloredStyles.length).toBeGreaterThan(0);

    for (const [mode, theme] of Object.entries(themeBlocks)) {
      const backgrounds = [
        resolveColor(theme, "var(--vui-surface-base)"),
        resolveColor(theme, "var(--vui-surface-row-hover)"),
      ];

      for (const color of coloredStyles) {
        const foreground = resolveColor(theme, color);
        for (const background of backgrounds) {
          expect(
            contrastRatio(foreground, background),
            `${mode} theme color ${color} on ${background}`,
          ).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });
});
