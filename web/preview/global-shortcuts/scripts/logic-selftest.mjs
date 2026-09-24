/**
 * 纯逻辑自检（预览专用，不进测试套件）：
 * 用 esbuild（web 既有依赖）把断言入口与 shortcuts 内核打包成 CJS 后由 node 执行。
 * 用法：node scripts/logic-selftest.mjs；全部断言通过退出码 0。
 */
import { buildSync } from "esbuild";
import { mkdtempSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const previewRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const assertionEntry = `
import { parseShortcutBinding, serializeShortcutBinding } from "./src/shortcuts/bindingFormat";
import { resolveEffectiveBindings } from "./src/shortcuts/commands";
import { checkBindingConflict } from "./src/shortcuts/conflicts";
import { matchesShortcutBinding, recordShortcutBinding } from "./src/shortcuts/useGlobalShortcuts";

let failures = 0;
function check(name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) { failures += 1; console.error("FAIL", name, "actual=", JSON.stringify(actual), "expected=", JSON.stringify(expected)); }
  else { console.log("ok", name); }
}

// ---- 绑定串解析/序列化 ----
check("parse CmdOrCtrl+k", parseShortcutBinding("CmdOrCtrl+k"), { cmdOrCtrl: true, ctrl: false, alt: false, shift: false, altGr: false, key: "k" });
check("parse 大写键归一", (parseShortcutBinding("CTRL+SHIFT+D") || {}).key, "d");
check("parse 重复修饰键拒绝", parseShortcutBinding("Ctrl+Ctrl+k"), null);
check("parse 非法键拒绝", parseShortcutBinding("CmdOrCtrl+%"), null);
check("serialize canonical 顺序", serializeShortcutBinding({ shift: true, altGr: false, ctrl: false, cmdOrCtrl: true, alt: false, key: "p" }), "CmdOrCtrl+Shift+p");
check("serialize 缺键名拒绝", serializeShortcutBinding({ shift: true, altGr: false, ctrl: false, cmdOrCtrl: true, alt: false, key: "" }), null);

// ---- 平台语义匹配 ----
const base = { key: "k", code: "KeyK", metaKey: false, ctrlKey: true, shiftKey: false, altKey: false };
check("win: Ctrl+K 命中 CmdOrCtrl+k", matchesShortcutBinding(base, "CmdOrCtrl+k", false), true);
check("win: Meta+K 不命中 CmdOrCtrl+k", matchesShortcutBinding({ ...base, ctrlKey: false, metaKey: true }, "CmdOrCtrl+k", false), false);
check("win: Ctrl+Shift+K 不命中（多余 shift）", matchesShortcutBinding({ ...base, shiftKey: true }, "CmdOrCtrl+k", false), false);
check("mac: Meta+K 命中", matchesShortcutBinding({ ...base, ctrlKey: false, metaKey: true }, "CmdOrCtrl+k", true), true);
check("mac: Ctrl+K 不命中 CmdOrCtrl+k", matchesShortcutBinding(base, "CmdOrCtrl+k", true), false);
check("event.key 大写命中（Shift 输入）", matchesShortcutBinding({ ...base, key: "K" }, "CmdOrCtrl+k", false), true);
check("code 兜底（key 被布局改写）", matchesShortcutBinding({ ...base, key: "\\u0153" }, "CmdOrCtrl+k", false), true);
check("长按 repeat 不命中", matchesShortcutBinding({ ...base, repeat: true }, "CmdOrCtrl+k", false), false);
check("IME keyCode 229 不命中", matchesShortcutBinding({ ...base, key: "Process", keyCode: 229 }, "CmdOrCtrl+k", false), false);
check("裸 Enter：Cmd+Enter 不误命中", matchesShortcutBinding({ key: "Enter", code: "Enter", ctrlKey: true, metaKey: false, shiftKey: false, altKey: false }, "Enter", false), false);
check("裸 Enter：裸按命中", matchesShortcutBinding({ key: "Enter", code: "Enter", ctrlKey: false, metaKey: false, shiftKey: false, altKey: false }, "Enter", false), true);

// ---- 录制器 ----
check("录制：纯修饰键 pending", recordShortcutBinding({ key: "Control", ctrlKey: true, metaKey: false, shiftKey: false, altKey: false }, false).kind, "pending");
check("录制：win Ctrl+J → CmdOrCtrl+j", recordShortcutBinding({ key: "j", code: "KeyJ", ctrlKey: true, metaKey: false, shiftKey: false, altKey: false }, false), { kind: "binding", binding: "CmdOrCtrl+j" });
check("录制：Shift+7 用 code 反查", recordShortcutBinding({ key: "&", code: "Digit7", ctrlKey: false, metaKey: false, shiftKey: true, altKey: false }, false), { kind: "binding", binding: "Shift+7" });
check("录制：无修饰字符键拒绝", recordShortcutBinding({ key: "g", code: "KeyG", ctrlKey: false, metaKey: false, shiftKey: false, altKey: false }, false), { kind: "invalid", reason: "no-modifier" });
check("录制：win 纯 Win 键组合拒绝（主修饰丢失）", recordShortcutBinding({ key: "j", code: "KeyJ", ctrlKey: false, metaKey: true, shiftKey: false, altKey: false }, false).kind, "invalid");

// ---- 生效表与覆盖 ----
const defaults = resolveEffectiveBindings();
check("生效表：默认回退", defaults.openCommandPalette, ["CmdOrCtrl+k"]);
check("生效表：显式空数组=清除不回退", resolveEffectiveBindings({ cycleDensity: [] }).cycleDensity, []);
check("生效表：覆盖整组替换", resolveEffectiveBindings({ openCommandPalette: ["Ctrl+Alt+k"] }).openCommandPalette, ["Ctrl+Alt+k"]);
check("生效表：非法条目逐条忽略", resolveEffectiveBindings({ openCommandPalette: ["\\u574f\\u7ed1\\u5b9a", "CmdOrCtrl+k"] }).openCommandPalette, ["CmdOrCtrl+k"]);
check("生效表：全部非法回退默认", resolveEffectiveBindings({ openCommandPalette: ["\\u574f\\u7ed1\\u5b9a"] }).openCommandPalette, ["CmdOrCtrl+k"]);

// ---- 冲突检测（win 口径） ----
const effective = resolveEffectiveBindings();
check("冲突：占用检测", checkBindingConflict("openSessionSearch", "CmdOrCtrl+k", effective, false), { kind: "occupied", binding: "CmdOrCtrl+k", ownerCommandId: "openCommandPalette", ownerTitle: "\\u6253\\u5f00\\u547d\\u4ee4\\u9762\\u677f" });
check("冲突：物理等价归一（Ctrl+k 等价 CmdOrCtrl+k）", (checkBindingConflict("openSessionSearch", "Ctrl+k", effective, false) || {}).kind, "occupied");
check("冲突：mac 上 Ctrl+k 与 CmdOrCtrl+k 不等价", checkBindingConflict("openSessionSearch", "Ctrl+k", effective, true), null);
check("冲突：保留键 Enter", checkBindingConflict("cycleDensity", "Enter", effective, false), { kind: "reserved", binding: "Enter" });
check("冲突：保留键编辑类", (checkBindingConflict("cycleDensity", "CmdOrCtrl+c", effective, false) || {}).kind, "reserved");
check("冲突：自身现有绑定不算冲突", checkBindingConflict("openCommandPalette", "CmdOrCtrl+k", effective, false), null);
check("冲突：空闲组合可绑", checkBindingConflict("cycleDensity", "Ctrl+Alt+g", effective, false), null);

if (failures > 0) {
  console.error(failures + " assertions failed");
  process.exit(1);
}
console.log("ALL PASS");
`;

const outDir = mkdtempSync(join(tmpdir(), "gsp-selftest-"));
const outFile = join(outDir, "selftest.cjs");

buildSync({
  stdin: {
    contents: assertionEntry,
    resolveDir: previewRoot,
    loader: "ts",
  },
  bundle: true,
  format: "cjs",
  platform: "node",
  outfile: outFile,
});

const result = spawnSync(process.execPath, [outFile], { encoding: "utf-8" });
process.stdout.write(result.stdout ?? "");
process.stderr.write(result.stderr ?? "");
process.exit(result.status ?? 1);
