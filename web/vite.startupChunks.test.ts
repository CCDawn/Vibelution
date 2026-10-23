import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { rolldown, type OutputChunk } from "rolldown";
import type { UserConfig } from "vite";
import { expect, it } from "vitest";

import viteConfig from "./vite.config";

it("coalesces initial shared modules while keeping route-only code lazy", async () => {
  const root = await mkdtemp(join(tmpdir(), "vibelution-startup-chunks-"));
  try {
    const source = join(root, "src");
    await mkdir(source);
    const imports: string[] = [];
    const labels: string[] = [];
    const loaders: string[] = [];
    for (let i = 0; i < 32; i++) {
      await writeFile(join(source, `shared-${i}.js`), `export const label${i} = "label-${i}";`);
      await writeFile(join(source, `route-${i}.js`), `export { label${i} } from "./shared-${i}.js"; export const body = "ROUTE_ONLY_${i}";`);
      imports.push(`import { label${i} } from "./shared-${i}.js";`);
      labels.push(`label${i}`);
      loaders.push(`() => import("./route-${i}.js")`);
    }
    await writeFile(join(source, "index.js"), `${imports.join("\n")} export const labels = [${labels}]; export const loaders = [${loaders}];`);
    const configured = (viteConfig as UserConfig).build?.rolldownOptions?.output;
    const output = Array.isArray(configured) ? configured[0] : configured;
    const splitting = output?.codeSplitting;
    if (!splitting || typeof splitting !== "object") throw new Error("Missing production code splitting");
    const initialGroup = splitting.groups?.find((group) => group.name === "initial-deps");
    if (!initialGroup) throw new Error("Missing initial shared group");

    async function build(groups: NonNullable<typeof splitting>["groups"]) {
      const bundle = await rolldown({ input: join(source, "index.js") });
      try {
        const result = await bundle.generate({ format: "esm", codeSplitting: { groups } });
        const chunks = result.output.filter((item): item is OutputChunk => item.type === "chunk");
        const entry = chunks.find((chunk) => chunk.isEntry);
        if (!entry) throw new Error("Entry must stay independently addressable");
        const byName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]));
        const initial = new Set<OutputChunk>();
        function visit(chunk: OutputChunk) {
          if (initial.has(chunk)) return;
          initial.add(chunk);
          for (const name of chunk.imports) {
            const dependency = byName.get(name);
            if (dependency) visit(dependency);
          }
        }
        visit(entry);
        return { chunks, initial: [...initial] };
      } finally {
        await bundle.close();
      }
    }

    const baseline = await build([]);
    const candidate = await build([initialGroup]);
    expect(baseline.initial.length).toBeGreaterThan(20);
    expect(candidate.initial.length).toBeLessThan(5);
    expect(candidate.initial.map((chunk) => chunk.code).join("\n")).not.toContain("ROUTE_ONLY_");
    for (let i = 0; i < 32; i++) {
      expect(candidate.chunks.some((chunk) => chunk.code.includes(`ROUTE_ONLY_${i}`))).toBe(true);
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
