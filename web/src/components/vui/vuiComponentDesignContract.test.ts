import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Every public VUI element needs a design spec entry (not only page recipes).
 * INDEX.md is the catalog; each entry points at a designs/** file with ## Name.
 */
const vuiRoot = resolve(import.meta.dirname);
const designsRoot = resolve(vuiRoot, "designs");
const indexPath = resolve(designsRoot, "INDEX.md");
const indexSource = readFileSync(resolve(vuiRoot, "index.ts"), "utf8");
const catalog = readFileSync(indexPath, "utf8");

function publicExportsFromIndexTs(source: string): string[] {
  const names = new Set<string>();
  const re = /export\s*\{([^}]+)\}/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(source))) {
    const block = match[1];
    for (const part of block.split(",")) {
      const token = part.trim();
      if (!token || token.startsWith("type ") || token.startsWith("type\t")) {
        continue;
      }
      const name = token.replace(/^type\s+/, "").split(/\s+as\s+/)[0]?.trim();
      if (!name) {
        continue;
      }
      // Public component-like symbols: V* product shells, aesthetic atoms, provider.
      // Components only — skip VUI_* class tokens and type-only noise.
      if (
        /^(V[A-Z][A-Za-z0-9]*|VuiProvider)$/.test(name)
        && !name.startsWith("VUI_")
      ) {
        names.add(name);
      }
    }
  }
  return [...names].sort();
}

function catalogComponents(source: string): Array<{ name: string; href: string }> {
  const rows: Array<{ name: string; href: string }> = [];
  // | `Name` | [text](./path.md#anchor) |
  const re = /\|\s*`([^`]+)`\s*\|\s*\[[^\]]*\]\(([^)]+)\)\s*\|/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(source))) {
    const raw = match[1].trim();
    // Skip rows like "TeamSourceResultList / TeamSourceResultItem"
    for (const name of raw.split(/\s*\/\s*/)) {
      const cleaned = name.trim();
      if (cleaned) {
        rows.push({ name: cleaned, href: match[2].trim() });
      }
    }
  }
  return rows;
}

function headingExists(filePath: string, componentName: string): boolean {
  if (!existsSync(filePath)) {
    return false;
  }
  const text = readFileSync(filePath, "utf8");
  // ## VButton or ## Component: `VButton`
  const patterns = [
    new RegExp(`^##\\s+${componentName}\\s*$`, "m"),
    new RegExp(`^##\\s+Component:\\s*\`${componentName}\`\\s*$`, "m"),
    new RegExp(`^##\\s+\`${componentName}\`\\s*$`, "m"),
  ];
  return patterns.some((re) => re.test(text));
}

describe("VUI component design contract", () => {
  it("ships designs catalog and template", () => {
    expect(existsSync(indexPath)).toBe(true);
    expect(existsSync(resolve(designsRoot, "README.md"))).toBe(true);
    expect(existsSync(resolve(designsRoot, "_TEMPLATE.md"))).toBe(true);
    expect(catalog).toContain("# VUI Component Index");
  });

  it("lists every public V* export from index.ts in INDEX.md", () => {
    const exported = publicExportsFromIndexTs(indexSource);
    const listed = new Set(catalogComponents(catalog).map((row) => row.name));
    const missing = exported.filter((name) => !listed.has(name));
    expect(missing, `Missing design INDEX entries:\n${missing.join("\n")}`).toEqual([]);
  });

  it("resolves every INDEX entry to an existing design section", () => {
    const rows = catalogComponents(catalog);
    expect(rows.length).toBeGreaterThan(30);
    const offenders: string[] = [];
    for (const row of rows) {
      const hrefPath = row.href.replace(/#.*$/, "").replace(/^\.\//, "");
      const filePath = resolve(designsRoot, hrefPath);
      if (!existsSync(filePath)) {
        offenders.push(`${row.name}: missing file ${hrefPath}`);
        continue;
      }
      if (!headingExists(filePath, row.name)) {
        offenders.push(`${row.name}: missing ## ${row.name} in ${hrefPath}`);
      }
    }
    expect(offenders, offenders.join("\n")).toEqual([]);
  });

  it("does not leave empty designs directories without markdown", () => {
    function walk(dir: string, out: string[] = []): string[] {
      for (const name of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, name.name);
        if (name.isDirectory()) {
          walk(full, out);
        } else if (name.name.endsWith(".md")) {
          out.push(full);
        }
      }
      return out;
    }
    const files = walk(designsRoot);
    expect(files.length).toBeGreaterThan(10);
  });
});
