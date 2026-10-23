import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { pathToFileURL } from "node:url";
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
    const reactPath = JSON.stringify(createRequire(import.meta.url).resolve("react"));
    for (let i = 0; i < 32; i++) {
      await writeFile(join(source, `shared-${i}.js`), `import { createContext } from ${reactPath}; export const label${i} = createContext("label-${i}");`);
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
        const result = await bundle.generate({
          format: "esm",
          strictExecutionOrder: output?.strictExecutionOrder,
          codeSplitting: { groups },
        });
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
        return { chunks, initial: [...initial], entry };
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
    // Exercise native ESM evaluation as well as graph shape. A split CommonJS
    // init helper must be initialized before React consumers call it.
    const stress = await build([{ ...initialGroup, maxSize: 1_000 }]);
    const emitted = join(root, "emitted");
    await mkdir(emitted);
    await writeFile(join(emitted, "package.json"), JSON.stringify({ type: "module" }));
    for (const chunk of stress.chunks) await writeFile(join(emitted, chunk.fileName), chunk.code);
    const entryUrl = JSON.stringify(pathToFileURL(join(emitted, stress.entry.fileName)).href);
    const script = `const entry = await import(${entryUrl}); const routes = await Promise.all(entry.loaders.map(load => load())); console.log(JSON.stringify({ labels: entry.labels.map(item => item._currentValue), bodies: routes.map(item => item.body) }));`;
    const { stdout } = await promisify(execFile)(process.execPath, ["--input-type=module", "-e", script], { windowsHide: true });
    expect(JSON.parse(stdout)).toEqual({
      labels: Array.from({ length: 32 }, (_, i) => `label-${i}`),
      bodies: Array.from({ length: 32 }, (_, i) => `ROUTE_ONLY_${i}`),
    });
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
