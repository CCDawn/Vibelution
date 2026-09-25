/**
 * 设置面对齐波次 1 —— 隔离预览应用（不进生产路由）。
 *
 * 演示三个对齐点（全部为前端模拟，数据照 EDITOR_SECTION_SPECS/ContextCompressionConfig）：
 * - A VSettingsRow 行原语（查看态）：label+说明在左、只读值在右、行间 border-t、
 *   组=圆角边框卡无阴影；顶部「卡片流/行列表」密度开关供 A/B 对比。
 * - B 控件升级（编辑态）：json 实时校验（红边+首个错误行列定位，合法显示
 *   「✓ 格式正确」）；number 步进器+min/max 硬校验+单位后缀；list 逐行校验
 *   （非法行标红+行号错误）；布尔/下拉保持 VCheckbox/VStringSelect。
 * - C 保存模型：行右侧徽标三态（无/已生效/待保存）；布尔/下拉=即时类，
 *   文本/数字/列表/json=草稿类；顶部常驻保存条（待保存 N 项、N=0 禁用）；
 *   模拟离开触发三选一 VUI 确认弹窗（保存/放弃/留下）。
 *
 * UI 只用 web/src/components/vui 的 V* 与 --vui-* 令牌；正式 designs 登记留给集成任务。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { VButton } from "../../../src/components/vui/primitives/VButton";
import { VChip } from "../../../src/components/vui/primitives/VChip";
import { VDialog } from "../../../src/components/vui/primitives/VDialog";
import { VCheckbox } from "../../../src/components/vui/forms/VCheckbox";
import { VInput } from "../../../src/components/vui/forms/VInput";
import { VStringSelect } from "../../../src/components/vui/forms/VStringSelect";
import { VTextarea } from "../../../src/components/vui/forms/VTextarea";
import {
  collectPendingItems,
  applyDraftSave,
  deriveRowStatus,
  formatFieldEditorText,
  validateJsonText,
  validateListText,
  validateNumberText,
  stepNumberValue,
  type FieldDeclaration,
} from "./settingsModel";
import {
  COPY,
  JSON_ERROR_SAMPLE,
  LIST_INVALID_SAMPLE,
  NOTES,
  PREVIEW_FIELDS,
  SECTION_SUBTITLE,
  SECTION_SUBTITLE_EN,
  SECTION_TITLE,
  SECTION_TITLE_EN,
  copyText,
  readPreviewBootState,
  type Lang,
  type PreviewBootState,
} from "./demoData";
import { VSettingsGroupCard, VSettingsRow } from "./VSettingsRow";

type Density = "rows" | "cards";
type Mode = "view" | "edit";
type Toast = { id: number; text: string };

type FieldValues = Record<string, unknown>;

/** 把 committed 运行时值转成草稿编辑串（number/json/list 都是文本形态）。 */
function buildEditorDrafts(fields: readonly FieldDeclaration[], values: FieldValues): FieldValues {
  const drafts: FieldValues = {};
  for (const field of fields) {
    if (field.saveMode !== "draft") {
      continue;
    }
    drafts[field.path] = formatFieldEditorText(field, values[field.path]);
  }
  return drafts;
}

function fieldLabel(field: FieldDeclaration, lang: Lang): string {
  return lang === "zh" ? field.label : field.labelEn;
}

function fieldDescription(field: FieldDeclaration, lang: Lang): string {
  return lang === "zh" ? field.description : field.descriptionEn;
}

function fieldUnit(field: FieldDeclaration, lang: Lang): string {
  if (field.kind !== "number") {
    return "";
  }
  return (lang === "zh" ? field.unit : field.unitEn) ?? field.unit ?? "";
}

function formatNumberValue(value: unknown): string {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  return numeric.toLocaleString("en-US");
}

/** 深链初始态：一次算出 committed+drafts，保证每个 state 首屏即现目标态。 */
function buildInitialState(boot: PreviewBootState): { committed: FieldValues; drafts: FieldValues } {
  const committed: FieldValues = {};
  for (const field of PREVIEW_FIELDS) {
    committed[field.path] = field.defaultValue;
  }
  if (boot === "edit-dirty") {
    // 即时类变更：已直接提交 → 「已生效」徽标。
    committed["context_compression.micro_compact_enabled"] = false;
  } else if (boot === "saved") {
    // 刚保存完：草稿已提交，徽标清除。
    committed["context_compression.max_token_limit"] = 24000;
  }
  const drafts = buildEditorDrafts(PREVIEW_FIELDS, committed);
  if (boot === "edit-dirty") {
    // 草稿类变更：未保存 → 「待保存」徽标 + 保存条计数。
    drafts["context_compression.max_token_limit"] = "24000";
  } else if (boot === "json-error") {
    drafts["context_compression.summary_chars"] = JSON_ERROR_SAMPLE;
  } else if (boot === "list-invalid") {
    drafts["context_compression.micro_compact_tool_whitelist"] = LIST_INVALID_SAMPLE;
  }
  return { committed, drafts };
}

export function PreviewApp() {
  const bootRef = useRef<PreviewBootState>(readPreviewBootState());
  const boot = bootRef.current;

  const [lang, setLang] = useState<Lang>("zh");
  const [density, setDensity] = useState<Density>(boot === "view-cards" ? "cards" : "rows");
  const [mode, setMode] = useState<Mode>(boot === "view-cards" || boot === "view-rows" ? "view" : "edit");

  // 基线（本页加载时的外部配置值）；保存时随 committed 重置 → 全部徽标清除。
  const [baseline, setBaseline] = useState<FieldValues>(() => {
    const values: FieldValues = {};
    for (const field of PREVIEW_FIELDS) {
      values[field.path] = field.defaultValue;
    }
    return values;
  });

  // 深链种子直接进首屏初始 state（无需挂载后再补丁）。
  const initialRef = useRef<{ committed: FieldValues; drafts: FieldValues } | null>(null);
  if (initialRef.current === null) {
    initialRef.current = buildInitialState(boot);
  }
  const [committed, setCommitted] = useState<FieldValues>(initialRef.current.committed);
  const [drafts, setDrafts] = useState<FieldValues>(initialRef.current.drafts);

  const [toast, setToast] = useState<Toast | null>(() =>
    boot === "saved" ? { id: 0, text: COPY.toastSaved.zh } : null,
  );
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);
  const toastSeq = useRef(0);

  // toast 自动退场（4.5s），与真实 toast 语义一致。
  useEffect(() => {
    if (toast === null) {
      return;
    }
    const timer = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const showToast = useCallback((text: string) => {
    toastSeq.current += 1;
    setToast({ id: toastSeq.current, text });
  }, []);

  const pendingItems = useMemo(
    () => collectPendingItems(PREVIEW_FIELDS, baseline, committed, drafts),
    [baseline, committed, drafts],
  );
  const pendingCount = pendingItems.length;
  const hasInvalidDraft = pendingItems.some((item) => !item.valid);

  /** 即时类变更：直接提交 committed（无 dirty 参与）。 */
  const commitImmediate = useCallback((path: string, value: unknown) => {
    setCommitted((prev) => ({ ...prev, [path]: value }));
  }, []);

  /** 草稿类变更：只进 draft 缓冲，等显式保存。 */
  const setDraft = useCallback((path: string, value: unknown) => {
    setDrafts((prev) => ({ ...prev, [path]: value }));
  }, []);

  const handleSave = useCallback(() => {
    const result = applyDraftSave(PREVIEW_FIELDS, committed, drafts);
    setCommitted(result.committed);
    if (result.blockedPaths.length > 0) {
      return;
    }
    // 保存 = 全部确认：草稿已提交、即时类基线同步重置，所有徽标清除。
    setBaseline(result.committed);
    showToast(copyText("toastSaved", lang));
  }, [committed, drafts, lang, showToast]);

  const handleDiscard = useCallback(() => {
    setDrafts(buildEditorDrafts(PREVIEW_FIELDS, committed));
    showToast(copyText("toastDiscarded", lang));
  }, [committed, lang, showToast]);

  const statusFor = useCallback(
    (field: FieldDeclaration) =>
      deriveRowStatus(field, baseline[field.path], committed[field.path], drafts[field.path]),
    [baseline, committed, drafts],
  );

  const statusBadge = useCallback(
    (field: FieldDeclaration) => {
      const status = statusFor(field);
      if (status === "clean") {
        return null;
      }
      if (status === "applied") {
        return (
          <VChip tone="accent" data-testid={`badge-${field.path}`} data-vui-status="applied">
            {copyText("statusApplied", lang)}
          </VChip>
        );
      }
      return (
        <span
          data-testid={`badge-${field.path}`}
          data-vui-status="pending"
          className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-vui-control border border-vui-border-subtle bg-vui-surface-inset px-2 py-0.5 text-vui-2xs font-medium text-vui-fg-secondary"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-vui-fg-secondary" />
          {copyText("statusPending", lang)}
        </span>
      );
    },
    [lang, statusFor],
  );

  /** 查看态只读值展示。 */
  const renderReadonlyValue = useCallback(
    (field: FieldDeclaration) => {
      const value = committed[field.path];
      if (field.kind === "boolean") {
        return (
          <VChip tone={value ? "success" : "neutral"} data-vui-readonly="boolean">
            {value ? copyText("booleanOn", lang) : copyText("booleanOff", lang)}
          </VChip>
        );
      }
      if (field.kind === "select") {
        const option = field.options?.find((candidate) => candidate.value === value);
        return <span className="text-vui-xs text-vui-fg-secondary">{option ? (lang === "zh" ? option.label : option.labelEn) : String(value)}</span>;
      }
      if (field.kind === "number") {
        return (
          <span className="text-vui-xs text-vui-fg-secondary">
            {formatNumberValue(value)}
            <span className="text-vui-fg-tertiary">{"\u00a0"}</span>
            <span className="text-vui-fg-tertiary">{fieldUnit(field, lang)}</span>
          </span>
        );
      }
      if (field.kind === "string_list") {
        const items = Array.isArray(value) ? value.map(String) : [];
        const preview = items.slice(0, 3).join("、");
        const rest = items.length > 3 ? ` …` : "";
        return (
          <span className="text-vui-xs text-vui-fg-secondary">
            <span className="font-medium text-vui-fg-primary">{items.length}</span>
            {copyText("itemsTotal", lang)}
            <span className="text-vui-fg-tertiary">{"\u00a0·\u00a0"}</span>
            <span className="text-vui-fg-tertiary">{preview}</span>
            {rest}
          </span>
        );
      }
      // json：单行摘要（查看态不展开编辑器）。
      const summary = JSON.stringify(value);
      return (
        <span className="block max-w-full truncate font-mono text-vui-2xs text-vui-fg-tertiary" title={summary}>
          {summary}
        </span>
      );
    },
    [committed, lang],
  );

  /** 编辑态控件（B 控件升级）。 */
  const renderEditControl = useCallback(
    (field: FieldDeclaration) => {
      if (field.kind === "boolean") {
        return (
          <VCheckbox
            isSelected={Boolean(committed[field.path])}
            onChange={(isSelected) => commitImmediate(field.path, isSelected)}
            data-testid={`control-${field.path}`}
            aria-label={fieldLabel(field, lang)}
          />
        );
      }
      if (field.kind === "select") {
        return (
          <VStringSelect
            ariaLabel={fieldLabel(field, lang)}
            value={String(committed[field.path] ?? "")}
            options={(field.options ?? []).map((option) => ({
              value: option.value,
              label: lang === "zh" ? option.label : option.labelEn,
            }))}
            onValueChange={(next) => commitImmediate(field.path, next)}
          />
        );
      }
      if (field.kind === "number") {
        return <NumberStepper field={field} drafts={drafts} committed={committed} lang={lang} onDraft={setDraft} />;
      }
      return (
        <span className="text-vui-2xs text-vui-fg-tertiary">
          {field.kind === "string_list"
            ? `${drafts[field.path] ? String(drafts[field.path]).split(/\r?\n/).filter((line) => line.trim() !== "").length : 0} ${copyText("itemsTotal", lang)}`
            : ""}
        </span>
      );
    },
    [commitImmediate, committed, drafts, lang, setDraft],
  );

  /** 宽编辑器（list/json）：渲染在行 footer，占满组卡宽度。 */
  const renderWideEditor = useCallback(
    (field: FieldDeclaration) => {
      const raw = typeof drafts[field.path] === "string" ? (drafts[field.path] as string) : "";
      if (field.kind === "json") {
        const result = validateJsonText(raw);
        return (
          <div className="grid gap-2">
            <VTextarea
              minRows={6}
              value={raw}
              aria-label={fieldLabel(field, lang)}
              data-testid={`editor-${field.path}`}
              aria-invalid={result.ok ? undefined : true}
              // vuiFormControlClass 自带固定高度类；宽编辑器按 rows 自然撑高。
              style={{ height: "auto" }}
              className={`font-mono text-vui-xs ${result.ok ? "" : "border-[var(--state-error)]"}`}
              onChange={(event) => setDraft(field.path, event.target.value)}
            />
            {result.ok ? (
              <p className="text-vui-xs text-vui-fg-tertiary" data-testid="json-status" data-vui-json="valid">
                {copyText("jsonValid", lang)}
              </p>
            ) : (
              <p className="text-vui-xs text-[var(--state-error)]" data-testid="json-status" data-vui-json="invalid">
                {copyText("jsonInvalidPrefix", lang)}
                {result.error}
                {result.line !== null
                  ? `${copyText("jsonErrorAt", lang)}${result.line}${copyText("jsonErrorLine", lang)}${result.column ?? "?"}${copyText("jsonErrorCol", lang)}`
                  : ""}
              </p>
            )}
          </div>
        );
      }
      if (field.kind === "string_list") {
        const validation = validateListText(raw);
        const lineCount = raw === "" ? 0 : raw.split(/\r?\n/).length;
        return (
          <div className="grid gap-2">
            <VTextarea
              minRows={Math.max(6, raw.split(/\r?\n/).length + 1)}
              value={raw}
              aria-label={fieldLabel(field, lang)}
              data-testid={`editor-${field.path}`}
              aria-invalid={validation.ok ? undefined : true}
              // vuiFormControlClass 自带固定高度类；宽编辑器按 rows 自然撑高。
              style={{ height: "auto" }}
              className={`font-mono text-vui-xs ${validation.ok ? "" : "border-[var(--state-error)]"}`}
              onChange={(event) => setDraft(field.path, event.target.value)}
            />
            <p className="text-vui-2xs text-vui-fg-tertiary" data-testid="list-stats">
              {lineCount} {copyText("listLineCount", lang)} ·{" "}
              {validation.lines.filter((line) => line.ok).length} {copyText("listValidCount", lang)}
              {validation.errorCount > 0
                ? ` · ${validation.errorCount} ${copyText("listErrorCount", lang)}`
                : ""}
            </p>
            {validation.lines.some((line) => !line.ok) ? (
              <ul className="grid gap-1" data-testid="list-errors">
                {validation.lines
                  .filter((line) => !line.ok)
                  .map((line) => (
                    <li key={line.line} className="text-vui-xs text-[var(--state-error)]">
                      {copyText("listLinePrefix", lang)}
                      {line.line}
                      {copyText("listLineMid", lang)}
                      {`「${line.value}」`}
                      {line.error}
                    </li>
                  ))}
              </ul>
            ) : null}
          </div>
        );
      }
      return null;
    },
    [drafts, lang, setDraft],
  );

  const openLeaveDialog = useCallback(() => {
    if (pendingCount > 0) {
      setLeaveDialogOpen(true);
      return;
    }
    // 无草稿：直接模拟离开成功。
    showToast(copyText("toastSavedLeave", lang));
  }, [lang, pendingCount, showToast]);

  const confirmLeaveSave = useCallback(() => {
    setLeaveDialogOpen(false);
    const result = applyDraftSave(PREVIEW_FIELDS, committed, drafts);
    setCommitted(result.committed);
    setDrafts(buildEditorDrafts(PREVIEW_FIELDS, result.committed));
    setBaseline(result.committed);
    showToast(copyText("toastSavedLeave", lang));
  }, [committed, drafts, lang, showToast]);

  const confirmLeaveDiscard = useCallback(() => {
    setLeaveDialogOpen(false);
    setDrafts(buildEditorDrafts(PREVIEW_FIELDS, committed));
    showToast(copyText("toastDiscardLeave", lang));
  }, [committed, lang, showToast]);

  const notes = NOTES[lang];

  return (
    <div
      data-vui-app="preview"
      className="grid min-h-screen content-start bg-vui-bg-canvas text-vui-fg-primary"
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-vui-border-subtle bg-vui-surface-panel px-6 py-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <strong className="text-vui-md font-semibold">
            {lang === "zh" ? SECTION_TITLE : SECTION_TITLE_EN}
          </strong>
          <VChip tone="neutral">{lang === "zh" ? SECTION_SUBTITLE : SECTION_SUBTITLE_EN}</VChip>
          <VChip tone="info">{copyText("badgePreview", lang)}</VChip>
          <VChip tone="neutral">{copyText("badgeBranch", lang)}</VChip>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className="text-vui-2xs text-vui-fg-tertiary">{copyText("densityLabel", lang)}</span>
          <VButton
            variant={density === "rows" ? "secondary" : "ghost"}
            density="compact"
            data-testid="density-rows"
            onClick={() => setDensity("rows")}
          >
            {copyText("densityRows", lang)}
          </VButton>
          <VButton
            variant={density === "cards" ? "secondary" : "ghost"}
            density="compact"
            data-testid="density-cards"
            onClick={() => setDensity("cards")}
          >
            {copyText("densityCards", lang)}
          </VButton>
          <span className="mx-1 h-4 w-px bg-vui-border-subtle" />
          <VButton
            variant={mode === "view" ? "secondary" : "ghost"}
            density="compact"
            data-testid="mode-view"
            onClick={() => setMode("view")}
          >
            {copyText("modeView", lang)}
          </VButton>
          <VButton
            variant={mode === "edit" ? "secondary" : "ghost"}
            density="compact"
            data-testid="mode-edit"
            onClick={() => setMode("edit")}
          >
            {copyText("modeEdit", lang)}
          </VButton>
          <span className="mx-1 h-4 w-px bg-vui-border-subtle" />
          <VButton
            variant={lang === "zh" ? "secondary" : "ghost"}
            density="compact"
            data-testid="lang-zh"
            onClick={() => setLang("zh")}
          >
            中
          </VButton>
          <VButton
            variant={lang === "en" ? "secondary" : "ghost"}
            density="compact"
            data-testid="lang-en"
            onClick={() => setLang("en")}
          >
            EN
          </VButton>
        </div>
      </header>

      {/* C 保存模型：常驻全局保存条。 */}
      <div
        data-testid="save-bar"
        className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-vui-border-subtle bg-vui-surface-card px-6 py-2"
      >
        <div className="flex items-center gap-2">
          <strong className="text-vui-xs font-medium">{copyText("saveBarTitle", lang)}</strong>
          <span
            data-testid="save-count"
            className={
              pendingCount > 0
                ? "text-vui-xs font-medium text-vui-fg-primary"
                : "text-vui-xs text-vui-fg-tertiary"
            }
          >
            {copyText("statusPending", lang)} {pendingCount} {copyText("saveBarCountSuffix", lang)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <VButton
            variant="ghost"
            density="compact"
            isDisabled={pendingCount === 0}
            data-testid="discard-all"
            onClick={handleDiscard}
          >
            {copyText("discardAll", lang)}
          </VButton>
          <VButton
            variant="primary"
            density="compact"
            isDisabled={pendingCount === 0 || hasInvalidDraft}
            disabledReason={hasInvalidDraft ? copyText("saveBlockedReason", lang) : undefined}
            data-testid="save-all"
            onClick={handleSave}
          >
            {copyText("saveAll", lang)}
          </VButton>
          <VButton
            variant="secondary"
            density="compact"
            data-testid="leave-simulate"
            onClick={openLeaveDialog}
          >
            {copyText("leaveSimulate", lang)}
          </VButton>
        </div>
      </div>

      <main className="mx-auto grid w-full max-w-4xl content-start gap-4 px-6 py-5">
        {density === "rows" ? (
          <VSettingsGroupCard testId="settings-group">
            {PREVIEW_FIELDS.map((field) => {
              const isWideEditor = mode === "edit" && (field.kind === "json" || field.kind === "string_list");
              return (
                <VSettingsRow
                  key={field.path}
                  testId={`row-${field.path}`}
                  label={fieldLabel(field, lang)}
                  description={fieldDescription(field, lang)}
                  status={statusBadge(field)}
                  controlLayout={field.kind === "number" && mode === "edit" ? "wide" : "default"}
                  control={mode === "edit" ? renderEditControl(field) : renderReadonlyValue(field)}
                  footer={isWideEditor ? renderWideEditor(field) : undefined}
                />
              );
            })}
          </VSettingsGroupCard>
        ) : (
          <div className="grid gap-3" data-testid="settings-cards">
            {PREVIEW_FIELDS.map((field) => {
              const isWideEditor = mode === "edit" && (field.kind === "json" || field.kind === "string_list");
              return (
                <div
                  key={field.path}
                  data-testid={`card-${field.path}`}
                  className="grid gap-3 rounded-vui-panel border border-vui-border-subtle bg-vui-surface-card px-4 py-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-vui-sm font-medium text-vui-fg-primary">
                        {fieldLabel(field, lang)}
                      </div>
                      <div className="mt-1 text-vui-xs leading-5 text-vui-fg-tertiary">
                        {fieldDescription(field, lang)}
                      </div>
                    </div>
                    {statusBadge(field)}
                  </div>
                  <div className="justify-self-start">
                    {mode === "edit" ? renderEditControl(field) : renderReadonlyValue(field)}
                  </div>
                  {isWideEditor ? renderWideEditor(field) : null}
                </div>
              );
            })}
          </div>
        )}

        {/* 底部说明区：如实标注模拟语义。 */}
        <section className="grid gap-2 rounded-vui-panel border border-vui-border-subtle bg-vui-surface-panel px-4 py-4">
          <strong className="text-vui-xs font-medium">{copyText("notesTitle", lang)}</strong>
          <ul className="grid gap-1.5">
            {notes.map((note) => (
              <li key={note} className="text-vui-2xs leading-5 text-vui-fg-tertiary">
                · {note}
              </li>
            ))}
          </ul>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-vui-2xs text-vui-fg-tertiary">
            <span>{copyText("footnoteState", lang)}：</span>
            {(
              [
                "view-cards",
                "view-rows",
                "edit-clean",
                "edit-dirty",
                "json-error",
                "list-invalid",
                "saved",
              ] as const
            ).map((state) => (
              <a
                key={state}
                href={`?state=${state}`}
                className="rounded-vui-control border border-vui-border-subtle bg-vui-surface-inset px-1.5 py-0.5 font-mono text-vui-2xs text-vui-fg-secondary hover:text-vui-fg-primary"
              >
                {state}
              </a>
            ))}
          </p>
        </section>
      </main>

      {/* 模拟离开确认（有草稿时三选一：保存/放弃/留下）。 */}
      <VDialog
        open={leaveDialogOpen}
        onOpenChange={setLeaveDialogOpen}
        title={copyText("dialogLeaveTitle", lang)}
        description={copyText("dialogLeaveDescription", lang)}
        data-testid="leave-dialog"
        footer={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <VButton
              variant="primary"
              density="compact"
              isDisabled={hasInvalidDraft}
              disabledReason={hasInvalidDraft ? copyText("saveBlockedReason", lang) : undefined}
              data-testid="leave-save"
              onClick={confirmLeaveSave}
            >
              {copyText("dialogSaveLeave", lang)}
            </VButton>
            <VButton
              variant="secondary"
              density="compact"
              data-testid="leave-discard"
              onClick={confirmLeaveDiscard}
            >
              {copyText("dialogDiscardLeave", lang)}
            </VButton>
            <VButton variant="ghost" density="compact" data-testid="leave-stay" onClick={() => setLeaveDialogOpen(false)}>
              {copyText("dialogStay", lang)}
            </VButton>
          </div>
        }
      />

      {toast ? (
        <div
          key={toast.id}
          role="status"
          data-testid="toast"
          className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-vui-panel border border-vui-border-subtle bg-vui-surface-overlay px-4 py-2 text-vui-xs font-medium text-vui-fg-primary shadow-lg"
        >
          {toast.text}
        </div>
      ) : null}
    </div>
  );
}

/** number 步进器（B 控件升级）：−/+ 按钮 + 输入框 + 单位后缀 + min/max 硬校验。 */
function NumberStepper({
  field,
  drafts,
  committed,
  lang,
  onDraft,
}: {
  field: FieldDeclaration;
  drafts: FieldValues;
  committed: FieldValues;
  lang: Lang;
  onDraft: (path: string, value: unknown) => void;
}) {
  const raw = typeof drafts[field.path] === "string" ? (drafts[field.path] as string) : String(committed[field.path] ?? "");
  const result = validateNumberText(raw, field);
  const step = field.step ?? 1;
  const rangeHint = `${copyText("numberRangeHint", lang)} ${field.min ?? "−∞"} ~ ${field.max ?? "+∞"} · ${copyText("numberStepHint", lang)} ±${step}`;
  return (
    <div className="grid">
      <div className="flex items-center justify-end gap-1.5">
        <VButton
          variant="secondary"
          density="compact"
          contentLayout="plain"
          aria-label="-"
          data-testid={`step-down-${field.path}`}
          isDisabled={!result.ok}
          onClick={() => {
            const current = result.ok ? result.value : 0;
            onDraft(field.path, String(stepNumberValue(current, field, -1)));
          }}
        >
          −
        </VButton>
        <VInput
          value={raw}
          inputMode="decimal"
          aria-label={fieldLabel(field, lang)}
          data-testid={`editor-${field.path}`}
          aria-invalid={result.ok ? undefined : true}
          className={`w-20 text-right ${result.ok ? "" : "border-[var(--state-error)]"}`}
          onChange={(event) => onDraft(field.path, event.target.value)}
        />
        <VButton
          variant="secondary"
          density="compact"
          contentLayout="plain"
          aria-label="+"
          data-testid={`step-up-${field.path}`}
          isDisabled={!result.ok}
          onClick={() => {
            const current = result.ok ? result.value : (field.min ?? 0);
            onDraft(field.path, String(stepNumberValue(current, field, 1)));
          }}
        >
          +
        </VButton>
        <span className="w-12 text-vui-2xs text-vui-fg-tertiary">{fieldUnit(field, lang)}</span>
      </div>
      <div className="mt-1 grid justify-items-end gap-0.5 text-right">
        <span className="text-vui-2xs text-vui-fg-tertiary">{rangeHint}</span>
        {result.ok ? null : (
          <span className="text-vui-2xs text-[var(--state-error)]" data-testid={`number-error-${field.path}`}>
            {result.error}
          </span>
        )}
      </div>
    </div>
  );
}
