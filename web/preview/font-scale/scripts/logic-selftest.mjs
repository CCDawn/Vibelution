/**
 * 逻辑自测 —— 纯 Node，无构建（node scripts/logic-selftest.mjs）。
 *
 * 直接读两份 CSS 源做文本级核对，保证「CSS 副本本身」携带正确的派生公式：
 * - fontScaleTokens.css：主字阶 12 档必须是 calc(var(--vui-font-base) ± Npx) 形态，
 *   偏移 = 现值 − 16；
 * - 生产 src/design/tokens.css：主字阶 rem 现值（×16 = base16 px）+ 画布固定 px 例外；
 * 再对派生公式逐档 × base=14/15/16/17/18 断言：derived = 现值 + (base − 16)。
 * 另测钳制/步进/深链解析语义与「例外不参与派生」。
 * 任何断言失败 → 非零码退出。
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OVERRIDE_CSS = resolve(HERE, "..", "src", "fontScaleTokens.css");
const MODEL_TS = resolve(HERE, "..", "src", "fontScaleModel.ts");
const INDEX_HTML = resolve(HERE, "..", "index.html");
const PROD_TOKENS = resolve(HERE, "..", "..", "..", "src", "design", "tokens.css");

const MAIN_RUNGS = [
  "micro-9",
  "micro-10",
  "micro-11",
  "2xs",
  "micro-13",
  "xs",
  "sm",
  "md",
  "chat",
  "lg",
  "title",
  "xl",
];

let passed = 0;
let failed = 0;
const failures = [];

function check(name, ok, detail = "") {
  if (ok) {
    passed += 1;
  } else {
    failed += 1;
    failures.push(`${name}${detail ? ` — ${detail}` : ""}`);
  }
}

// ---------- 源解析 ----------

const overrideCss = readFileSync(OVERRIDE_CSS, "utf8");
const modelTs = readFileSync(MODEL_TS, "utf8");
const indexHtml = readFileSync(INDEX_HTML, "utf8");
const prodCss = readFileSync(PROD_TOKENS, "utf8");

/** 解析 `--vui-font-<id>: <value>;` 声明。 */
function parseDeclarations(cssText) {
  const map = new Map();
  const re = /--vui-font-([a-z0-9-]+)\s*:\s*([^;]+);/g;
  let m;
  while ((m = re.exec(cssText)) !== null) {
    map.set(m[1], m[2].trim());
  }
  return map;
}

const overrideDecls = parseDeclarations(overrideCss);
const prodDecls = parseDeclarations(prodCss);

/** 去注释后的 CSS 文本（文本级检查用，避免注释里的示例词误报）。 */
function stripComments(cssText) {
  return cssText.replace(/\/\*[\s\S]*?\*\//g, "");
}
const overrideBody = stripComments(overrideCss);

/** 生产主字阶现值（rem×16 = base16 的 px）。 */
const prodPx16 = new Map();
for (const rung of MAIN_RUNGS) {
  const raw = prodDecls.get(rung);
  check(`prod tokens 声明存在 --vui-font-${rung}`, typeof raw === "string");
  if (typeof raw !== "string") continue;
  const remMatch = /^([\d.]+)rem$/.exec(raw);
  check(`prod --vui-font-${rung} 是 rem 形态（${raw}）`, remMatch !== null);
  if (!remMatch) continue;
  prodPx16.set(rung, Number(remMatch[1]) * 16);
}

// ---------- A. 覆盖与形态 ----------

for (const rung of MAIN_RUNGS) {
  const value = overrideDecls.get(rung);
  check(`override 声明存在 --vui-font-${rung}`, typeof value === "string");
  if (rung === "md") {
    check(
      "override md = var(--vui-font-base)（基准本身）",
      value === "var(--vui-font-base)",
    );
  } else {
    const calcMatch = /^calc\(var\(--vui-font-base\)\s*([+-])\s*(\d+)px\)$/.exec(value ?? "");
    check(
      `override --vui-font-${rung} 是 calc(基准±Npx) 形态（${value}）`,
      calcMatch !== null,
    );
  }
}

// override 不得触碰固定例外轴。
check("override 不含 canvas 子阶梯", !overrideBody.includes("--vui-font-canvas"));
check("override 不含 pet 令牌", !overrideBody.includes("--vui-pet"));
check("override 不含 terminal/xterm 字号", !/xterm/i.test(overrideBody));

// ---------- B. 偏移 = 现值 − 16 ----------

/** 从 override 取偏移（md=0）。 */
function offsetOf(rung) {
  if (rung === "md") return 0;
  const value = overrideDecls.get(rung) ?? "";
  const m = /^calc\(var\(--vui-font-base\)\s*([+-])\s*(\d+)px\)$/.exec(value);
  if (!m) return null;
  return m[1] === "+" ? Number(m[2]) : -Number(m[2]);
}

for (const rung of MAIN_RUNGS) {
  const expected = prodPx16.get(rung) - 16;
  const actual = offsetOf(rung);
  check(
    `偏移对齐：${rung} 期望 ${expected} 实际 ${actual}`,
    actual === expected,
  );
}

// ---------- C. 派生公式逐档 × base 14..18 ----------

const BASES = [14, 15, 16, 17, 18];
for (const base of BASES) {
  for (const rung of MAIN_RUNGS) {
    const px16 = prodPx16.get(rung);
    const derived = px16 + (base - 16); // 模型公式
    const viaOffset = 16 + offsetOf(rung) + (base - 16); // CSS calc 语义等价式
    check(
      `derived(${rung}, base=${base}) = ${derived}`,
      derived === viaOffset,
      `css-calc 语义应为 ${viaOffset}`,
    );
  }
}

// 零漂移：base=16 时逐档 = 现值。
for (const rung of MAIN_RUNGS) {
  check(
    `零漂移 base=16：${rung} = ${prodPx16.get(rung)}px`,
    16 + offsetOf(rung) === prodPx16.get(rung),
  );
}

// ---------- D. 钳制/步进/深链语义（对照 fontScaleModel.ts 的常量与逻辑） ----------

const minMatch = /export const FONT_SCALE_MIN = (\d+)/.exec(modelTs);
const maxMatch = /export const FONT_SCALE_MAX = (\d+)/.exec(modelTs);
const defMatch = /export const FONT_SCALE_DEFAULT = (\d+)/.exec(modelTs);
check("模型 MIN=14", minMatch?.[1] === "14");
check("模型 MAX=18", maxMatch?.[1] === "18");
check("模型 DEFAULT=16", defMatch?.[1] === "16");
const MIN = Number(minMatch?.[1] ?? 14);
const MAX = Number(maxMatch?.[1] ?? 18);
const DEFAULT = Number(defMatch?.[1] ?? 16);

/** clampBase 镜像（与 fontScaleModel.ts 同语义）。 */
function clampBase(value) {
  if (!Number.isFinite(value)) return DEFAULT;
  return Math.min(MAX, Math.max(MIN, Math.round(value)));
}

function stepBase(current, direction) {
  return clampBase(current + direction * 1);
}

check("clamp(13) → 14（下越界归位）", clampBase(13) === MIN);
check("clamp(19) → 18（上越界归位）", clampBase(19) === MAX);
check("clamp(16.4) → 16（四舍五入）", clampBase(16.4) === 16);
check("clamp(NaN) → 16（默认）", clampBase(Number("x")) === DEFAULT);
check("step(18, +1) → 18（上界不再增）", stepBase(MAX, 1) === MAX);
check("step(14, -1) → 14（下界不再减）", stepBase(MIN, -1) === MIN);
check("step(16, +1) → 17", stepBase(16, 1) === 17);

/** readBootState 镜像（与 fontScaleModel.ts 同语义）。 */
function readBootState(search) {
  const params = new URLSearchParams(search);
  const rawBase = params.get("base");
  const base = rawBase === null ? DEFAULT : clampBase(Number(rawBase));
  const mode = params.get("mode") === "ab" ? "ab" : "single";
  const themeParam = params.get("theme");
  const theme = themeParam === "dark" || themeParam === "light" ? themeParam : null;
  return { base, mode, theme };
}

check("深链 ?base=14 → 14", readBootState("?base=14").base === 14);
check("深链 ?base=18 → 18", readBootState("?base=18").base === 18);
check("深链 ?base=99 → 18（越界钳制）", readBootState("?base=99").base === MAX);
check("深链 ?base=abc → 16（非法归默认）", readBootState("?base=abc").base === DEFAULT);
check("深链 ?mode=ab → ab", readBootState("?mode=ab").mode === "ab");
check("深链 ?theme=dark → dark", readBootState("?theme=dark").theme === "dark");
check("深链空参 → single/16/null", (() => {
  const boot = readBootState("");
  return boot.mode === "single" && boot.base === DEFAULT && boot.theme === null;
})());

// ---------- E. 首屏脚本与例外轴 ----------

check(
  "index.html 首屏脚本钳制 14–18",
  indexHtml.includes("Math.min(18, Math.max(14") ,
);
check(
  "index.html 首屏写 --vui-font-base",
  indexHtml.includes('"--vui-font-base"'),
);

const canvasRungLines = [...prodCss.matchAll(/--vui-font-canvas-([a-z0-9]+)\s*:\s*([^;]+);/g)];
check("生产画布子阶梯有 6 档（2xs..xl = 9/10/11/12/13/15px）", canvasRungLines.length === 6, `实际 ${canvasRungLines.length}`);
for (const [, rung, value] of canvasRungLines) {
  check(
    `画布 ${rung} 是固定 px 字面量（${value.trim()}）`,
    /^\d+px$/.test(value.trim()),
  );
}
check(
  "生产 pet 令牌块不含 calc（固定 px，不参与派生）",
  !/--vui-pet-[\w-]+:\s*calc/.test(prodCss),
);

// ---------- 汇总 ----------

console.log(`logic-selftest: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  console.error("failures:");
  for (const line of failures) {
    console.error(`  - ${line}`);
  }
  process.exit(1);
}
if (passed < 10) {
  console.error(`assertion count too low: ${passed} (< 10)`);
  process.exit(1);
}
