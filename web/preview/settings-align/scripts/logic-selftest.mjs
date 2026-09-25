/**
 * 纯逻辑自检（预览专用，不进测试套件）：
 * 用 esbuild（web 既有依赖）把断言入口与 settingsModel 内核打包成 CJS 后由 node 执行。
 * 用法：node scripts/logic-selftest.mjs；全部断言通过退出码 0。
 * 覆盖：json/list/number 校验、步进器、行状态机（即时/草稿）、保存流转（应用/阻塞）、
 * 待保存计数与文本归一化。
 */
import { buildSync } from "esbuild";
import { mkdtempSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const previewRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const assertionEntry = `
import {
  applyDraftSave,
  collectPendingItems,
  deriveRowStatus,
  formatFieldEditorText,
  stepNumberValue,
  validateJsonText,
  validateListText,
  validateNumberText,
} from "./src/settingsModel";
import { JSON_ERROR_SAMPLE, LIST_INVALID_SAMPLE, PREVIEW_FIELDS } from "./src/demoData";

let failures = 0;
function check(name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) { failures += 1; console.error("FAIL", name, "actual=", JSON.stringify(actual), "expected=", JSON.stringify(expected)); }
  else { console.log("ok", name); }
}
function checkTrue(name, actual) { check(name, actual, true); }
function checkFalse(name, actual) { check(name, actual, false); }

const byPath = Object.fromEntries(PREVIEW_FIELDS.map((f) => [f.path, f]));
const numberField = byPath["context_compression.max_token_limit"];
const charsField = byPath["context_compression.summary_chars"];
const listField = byPath["context_compression.micro_compact_tool_whitelist"];
const enabledField = byPath["context_compression.enabled"];

// ---- B: json 实时校验（不再静默存原始串） ----
const jsonOk = validateJsonText(JSON.stringify({ light: 500, standard: 1000 }));
checkTrue("json 合法串通过", jsonOk.ok);
check("json 合法串解析为对象", jsonOk.ok ? jsonOk.value : null, { light: 500, standard: 1000 });
const jsonBad = validateJsonText(JSON_ERROR_SAMPLE);
checkFalse("json 非法串（尾逗号）拒绝", jsonBad.ok);
checkTrue("json 非法串给出错误文案", !jsonBad.ok && jsonBad.error.length > 0);
if (!jsonBad.ok) {
  check("json 错误定位行", jsonBad.line, 6);
  check("json 错误定位列", jsonBad.column, 1);
}

// ---- B: number min/max 硬校验 + 步进器 ----
checkTrue("number 区间内通过", validateNumberText("16000", numberField).ok);
checkFalse("number 低于 min 拒绝", validateNumberText("999", numberField).ok);
checkFalse("number 高于 max 拒绝", validateNumberText("200001", numberField).ok);
checkFalse("number 非数字拒绝", validateNumberText("abc", numberField).ok);
const overMax = validateNumberText("200001", numberField);
checkTrue("number 错误文案给出边界", !overMax.ok && (overMax.error.includes("200000") || overMax.error.includes("最大值")));
check("step +1000", stepNumberValue(16000, numberField, 1), 17000);
check("step 上边界夹紧", stepNumberValue(200000, numberField, 1), 200000);
check("step 下边界夹紧", stepNumberValue(1000, numberField, -1), 1000);

// ---- B: list 逐行校验（非法行标红+行号） ----
const listOk = validateListText("read_file_tool\\nweb_search_tool");
checkTrue("list 全法行通过", listOk.ok);
check("list 解析值数组", listOk.values, ["read_file_tool", "web_search_tool"]);
const listBad = validateListText(LIST_INVALID_SAMPLE);
checkFalse("list 非法样例拒绝", listBad.ok);
check("list 非法行计数", listBad.errorCount, 2);
checkTrue("list 非法行带行号", listBad.lines.filter((l) => !l.ok).map((l) => l.line).includes(2));
const dup = validateListText("read_file_tool\\nread_file_tool");
check("list 重复项判非法", dup.errorCount, 1);
check("list 空行跳过不计数", validateListText("read_file_tool\\n\\nexec_command").lines.length, 2);

// ---- C: 行状态机（即时/草稿双轨） ----
const baseline = Object.fromEntries(PREVIEW_FIELDS.map((f) => [f.path, f.defaultValue]));
check("即时字段未变更=clean", deriveRowStatus(enabledField, baseline[enabledField.path], true, null), "clean");
check("即时字段已变更=applied", deriveRowStatus(enabledField, baseline[enabledField.path], false, null), "applied");
check("草稿字段未改（文本归一）=clean", deriveRowStatus(numberField, baseline[numberField.path], 16000, "16000"), "clean");
check("草稿字段已改=pending", deriveRowStatus(numberField, baseline[numberField.path], 16000, "24000"), "pending");
check("草稿字段非法输入=pending", deriveRowStatus(charsField, baseline[charsField.path], charsField.defaultValue, JSON_ERROR_SAMPLE), "pending");

// ---- C: 待保存计数与保存流转 ----
const committed0 = { ...baseline };
const drafts0 = {
  ...Object.fromEntries(PREVIEW_FIELDS.filter((f) => f.saveMode === "draft").map((f) => [f.path, formatFieldEditorText(f, committed0[f.path])])),
  "context_compression.max_token_limit": "24000",
};
const pending0 = collectPendingItems(PREVIEW_FIELDS, baseline, committed0, drafts0);
check("待保存计数=1", pending0.length, 1);
checkTrue("待保存项合法可保存", pending0.length === 1 && pending0[0].valid);
const save1 = applyDraftSave(PREVIEW_FIELDS, committed0, drafts0);
check("保存应用路径", save1.appliedPaths, ["context_compression.max_token_limit"]);
check("保存后 committed 更新", save1.committed["context_compression.max_token_limit"], 24000);
check("保存后徽标清除（归一比较）", deriveRowStatus(numberField, baseline[numberField.path], save1.committed["context_compression.max_token_limit"], drafts0["context_compression.max_token_limit"]), "clean");

// 非法草稿：保存被阻塞且不吞错误
const draftsBad = {
  ...drafts0,
  "context_compression.summary_chars": JSON_ERROR_SAMPLE,
};
const pendingBad = collectPendingItems(PREVIEW_FIELDS, baseline, committed0, draftsBad);
check("非法草稿计入待保存", pendingBad.length, 2);
checkTrue("非法草稿标记 invalid", pendingBad.some((item) => item.path === charsField.path && item.valid === false));
const save2 = applyDraftSave(PREVIEW_FIELDS, committed0, draftsBad);
check("合法草稿仍被应用", save2.appliedPaths.includes("context_compression.max_token_limit"), true);
check("非法草稿被阻塞", save2.blockedPaths, [charsField.path]);
checkFalse("非法草稿不写 committed", save2.committed["context_compression.summary_chars"] === JSON_ERROR_SAMPLE);

if (failures > 0) {
  console.error("selftest failed:", failures);
  process.exit(1);
}
console.log("all assertions passed");
`;

function main() {
  const result = buildSync({
    stdin: {
      contents: assertionEntry,
      resolveDir: previewRoot,
      sourcefile: "selftest-entry.ts",
      loader: "ts",
    },
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node22",
    write: false,
    logLevel: "silent",
  });
  const outFile = join(mkdtempSync(join(tmpdir(), "settings-align-selftest-")), "selftest.cjs");
  writeFileSync(outFile, result.outputFiles[0].text);
  const run = spawnSync(process.execPath, [outFile], { encoding: "utf8" });
  process.stdout.write(run.stdout);
  process.stderr.write(run.stderr);
  return run.status ?? 1;
}

process.exitCode = main();
