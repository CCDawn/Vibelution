import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { basename, extname, join, relative } from "node:path";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { fileURLToPath } from "node:url";

const sourceRoot = fileURLToPath(new URL("../../", import.meta.url));
const packageJsonPath = fileURLToPath(new URL("../../../package.json", import.meta.url));
const heroUiImportToken = "@heroui/react";
const vuiRendererRelativeRoot = "components/vui/renderers/";
const vuiProductRelativeRoot = "components/vui/product/";
const routeSourceExtensions = new Set([".ts", ".tsx"]);
const routeVisualUtilityPattern =
  /className\s*=\s*(?:["'`][^"'`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^"'`]*["'`]|{`[^`]*(?:bg-|text-|border-|rounded-|shadow-|px-|py-|gap-|grid|flex)[^`]*`})/;
const localVisualClassConstantPattern = /const\s+[A-Za-z0-9_]+Class\s*=/;
const localStylesObjectPattern = /const\s+styles\s*=/;
const parentRouteStyleImportPattern = /from\s+["']\.\/([A-Za-z0-9]+Route)\.styles["']/g;
const productSharedParentStyleConsumers = [
  "routes/chat/CacheDetailDialog.tsx",
  "routes/chat/ChatConversationIndexRail.tsx",
  "routes/chat/chatRoutePresentation.tsx",
  "routes/chat/ChatStatusRail.tsx",
  "routes/chat/TokenCoreStatusPanel.tsx",
  "routes/chat/useChatWorkbenchLayout.ts",
] as const;

function walkFiles(dir: string): string[] {
  const entries = readdirSync(dir);
  return entries.flatMap((entry) => {
    const fullPath = join(dir, entry);
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      return walkFiles(fullPath);
    }
    return /\.(ts|tsx|css)$/.test(entry) ? [fullPath] : [];
  });
}

function readText(file: string): string {
  return readFileSync(file, "utf-8");
}

function relativeFromSourceRoot(file: string): string {
  return relative(sourceRoot, file).replace(/\\/g, "/");
}

describe("VUI architecture boundary", () => {
  it("keeps @heroui/react out of package.json and source imports", () => {
    const packageJson = readText(packageJsonPath);
    expect(packageJson).not.toContain(heroUiImportToken);

    const boundarySelf = relativeFromSourceRoot(fileURLToPath(import.meta.url)).replace(/\\/g, "/");
    const offenders = walkFiles(sourceRoot)
      .filter((file) => readText(file).includes(heroUiImportToken))
      .map(relativeFromSourceRoot)
      .filter((file) => file !== boundarySelf && !file.endsWith("vuiImportBoundary.test.ts"));

    expect(offenders).toEqual([]);
  });

  it("documents the root provider as a VUI/shadcn boundary", () => {
    const providerSource = readText(join(sourceRoot, "components", "vui", "VuiProvider.tsx"));
    const mainSource = readText(join(sourceRoot, "main.tsx"));

    expect(providerSource).toContain("export function VuiProvider");
    expect(providerSource).toContain('data-vui-provider="shadcn"');
    expect(mainSource).toContain('from "./components/vui/VuiProvider"');
    expect(mainSource).toContain("vui-provider-theme.css");
    expect(mainSource).not.toContain("heroui-theme.css");
    expect(mainSource).not.toContain("renderers/heroui");
  });

  it("keeps VUI product components from importing renderer backends directly", () => {
    const offenders = walkFiles(join(sourceRoot, "components", "vui", "product"))
      .filter((file) => {
        const text = readText(file);
        return text.includes(heroUiImportToken) || /from\s+["'][^"']*renderers\/shadcn\//.test(text);
      })
      .map(relativeFromSourceRoot)
      .filter((file) => !file.startsWith(vuiRendererRelativeRoot))
      .filter((file) => file.startsWith(vuiProductRelativeRoot));

    expect(offenders).toEqual([]);
  });

  it("keeps routes from importing VUI renderers or shadcn backends directly", () => {
    const rendererImportPattern = /from\s+["'][^"']*components\/vui\/renderers\//;
    const offenders = walkFiles(join(sourceRoot, "routes"))
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !file.endsWith(".test.ts") && !file.endsWith(".test.tsx"))
      .filter((file) => rendererImportPattern.test(readText(join(sourceRoot, file))));

    expect(offenders).toEqual([]);
  });

  it("documents the VUI facade + shadcn renderer ownership model", () => {
    const readme = readText(join(sourceRoot, "components", "vui", "README.md"));
    expect(readme).toContain("stable product API");
    expect(readme).toContain("shadcn-style + Radix is the preferred implementation backend");
    expect(readme).toContain("No new `V*` primitive");
    expect(readme).toContain("VButton");
    expect(readme).toContain("ShadcnButton");
    expect(readme).toContain("VListDetailPage");
  });

  it("keeps interactive form primitives on the shadcn renderer path", () => {
    const button = readText(join(sourceRoot, "components", "vui", "primitives", "VButton.tsx"));
    const input = readText(join(sourceRoot, "components", "vui", "forms", "VInput.tsx"));
    const select = readText(join(sourceRoot, "components", "vui", "forms", "VSelect.tsx"));
    const checkbox = readText(join(sourceRoot, "components", "vui", "forms", "VCheckbox.tsx"));
    const tooltip = readText(join(sourceRoot, "components", "vui", "primitives", "VTooltip.tsx"));
    const dialog = readText(join(sourceRoot, "components", "vui", "primitives", "VDialog.tsx"));

    expect(button).toContain("ShadcnButton");
    expect(input).toContain("ShadcnInput");
    expect(select).toContain("ShadcnSelect");
    expect(checkbox).toContain("ShadcnCheckbox");
    expect(tooltip).toContain("ShadcnTooltip");
    expect(dialog).toContain("ShadcnDialog");
    expect(dialog).toContain("export function VConfirmDialog");
  });

  it("keeps product source files from adding inline Tailwind visual utility strings", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !file.endsWith(".test.tsx"))
      .filter((file) => !file.endsWith(".test.ts"))
      .filter((file) => routeVisualUtilityPattern.test(readText(join(sourceRoot, file))))

    expect(offenders).toEqual([]);
  });

  it("keeps product source files from owning local visual class constants", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const allowedSuffixes = [
      ".styles.ts",
      ".test.ts",
      ".test.tsx",
    ];
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => localVisualClassConstantPattern.test(readText(join(sourceRoot, file))));

    expect(offenders).toEqual([]);
  });

  it("keeps product source files from owning local styles objects", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const allowedSuffixes = [
      ".styles.ts",
      ".test.ts",
      ".test.tsx",
    ];
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => localStylesObjectPattern.test(readText(join(sourceRoot, file))));

    expect(offenders).toEqual([]);
  });

  it("keeps parent route style imports bounded to the migration allow-list", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const allowedSuffixes = [
      ".styles.ts",
      ".test.ts",
      ".test.tsx",
    ];
    const allowedSharedConsumers = new Set<string>(productSharedParentStyleConsumers);
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => {
        const source = readText(join(sourceRoot, file));
        return [...source.matchAll(parentRouteStyleImportPattern)].some((match) => basename(file) !== `${match[1]}.tsx`);
      })
      .filter((file) => !allowedSharedConsumers.has(file));

    expect(offenders).toEqual([]);
  });

  it("keeps parent style-map sharing explicitly bounded to known surface subcomponents", () => {
    const allowedRoots = [
      "components/vui/",
    ];
    const allowedSuffixes = [
      ".styles.ts",
      ".test.ts",
      ".test.tsx",
    ];
    const allowedSharedConsumers = new Set<string>(productSharedParentStyleConsumers);
    const offenders = walkFiles(sourceRoot)
      .filter((file) => routeSourceExtensions.has(extname(file)))
      .map(relativeFromSourceRoot)
      .filter((file) => !allowedRoots.some((root) => file.startsWith(root)))
      .filter((file) => !allowedSuffixes.some((suffix) => file.endsWith(suffix)))
      .filter((file) => {
        const source = readText(join(sourceRoot, file));
        return source.includes("className=") || source.includes("styles.");
      })
      .filter(
        (file) =>
          !existsSync(join(sourceRoot, file.replace(/\.tsx?$/, ".styles.ts"))) &&
          !existsSync(join(sourceRoot, file.replace(/\.tsx?$/, ".module.css"))),
      )
      .filter((file) => !allowedSharedConsumers.has(file));

    expect(offenders).toEqual([]);
  });
});
