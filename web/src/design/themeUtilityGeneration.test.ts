import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { compile } from "tailwindcss";
import { describe, expect, it } from "vitest";

const designRoot = import.meta.dirname;
const theme = readFileSync(resolve(designRoot, "theme.tailwind.css"), "utf8");

describe("production Tailwind semantic utilities", () => {
  it("generates the colors used by route-only surfaces and state variants", async () => {
    const compiler = await compile(`${theme}\n@tailwind utilities;`);
    const css = compiler.build([
      "hover:bg-vui-control-muted-hover",
      "bg-vui-surface-overlay",
      "!bg-vui-surface-base",
      "data-[source=other]:bg-vui-fg-tertiary",
      "border-vui-surface-rail",
    ]);
    for (const declaration of [
      "background-color: var(--vui-control-hover-bg)",
      "background-color: var(--vui-surface-overlay)",
      "background-color: var(--vui-surface-base)",
      "background-color: var(--fg-tertiary)",
      "border-color: var(--vui-surface-rail)",
    ]) expect(css).toContain(declaration);
  });

  it("loads the same theme in every independently compiled production entry", () => {
    expect(readFileSync(resolve(designRoot, "tailwind.css"), "utf8"))
      .toContain('@import "./theme.tailwind.css";');
    const routeRoot = resolve(designRoot, "route-css");
    for (const name of readdirSync(routeRoot).filter((name) => name.endsWith(".tailwind.css"))) {
      expect(readFileSync(resolve(routeRoot, name), "utf8"), name)
        .toContain('@import "../theme.tailwind.css";');
    }
  });
});
