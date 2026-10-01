/**
 * Pure apply-request builders for ConfigRoute.
 * React state and syncWorkspace remain on the route.
 */
import type {
  ConfigDraftMeta,
  ConfigEditorSection,
  ConfigWorkspace,
} from "../../api/types";
import {
  buildConfigApplyPayload,
  type PublicConfigShape,
} from "../configRouteLogic";

export type ConfigApplyDraftOverride = Pick<
  ConfigWorkspace,
  "publicConfig" | "draftMeta" | "baseHash"
>;

export type ConfigApplyRequestPayload = {
  publicConfig: PublicConfigShape;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  baseConfig: PublicConfigShape | null;
};

export function isConfigBaselineStaleErrorMessage(message: string): boolean {
  return /配置基线已过期|edit baseline is stale/i.test(String(message || ""));
}

const IMMEDIATE_APPLY_ROOTS = new Set(["ui", "user_profile", "avatar", "pet"]);

/**
 * Field-level save-mode declaration — single source of truth for the row save
 * model (settings-align wave 1): boolean/select fields are immediate (the view
 * row hosts a live control and every change goes through draft save + apply),
 * everything else is draft-based (section edit state, explicit save).
 */
const IMMEDIATE_FIELD_KINDS = new Set(["boolean", "select"]);

/**
 * ui.language 的专用写入端点（单一写入方声明）：界面语言切换只走
 * PUT /api/config/language（web/src/api/config.ts 的 updateConfigLanguage），
 * 改完即时生效，禁止再流入通用 immediate-apply / 分区草稿管线。
 * 原因：ui 属于 IMMEDIATE_APPLY_ROOTS、select 属于 IMMEDIATE_FIELD_KINDS，
 * 语言改动曾经由 preview + 整份配置 apply 写盘（language="en" 写进 operator
 * 配置导致整界面变英文的事故）；配套后端 apply 守卫同时负责在 apply payload
 * 里保留存量语言，前端在此从声明源头切断写入路径。
 */
export const UI_LANGUAGE_FIELD_PATH = "ui.language";

export function isUiLanguageFieldPath(path: string): boolean {
  return path === UI_LANGUAGE_FIELD_PATH;
}

/** Row badge lifecycle for an immediate-kind field change. */
export type ImmediateFieldStatus = "waiting" | "applied" | "failed";

/** Immediate-kind fields apply inline; all other kinds buffer as drafts. */
export function shouldImmediateApplyFieldKind(
  kind: string | undefined | null,
  path?: string,
): boolean {
  // ui.language 有专用语言端点（单一写入方，见上），不属于通用 immediate-apply。
  if (path && isUiLanguageFieldPath(path)) {
    return false;
  }
  return IMMEDIATE_FIELD_KINDS.has(String(kind || ""));
}

/**
 * Section-level immediate roots: sections under these paths keep applying the
 * whole working draft on section save (existing behavior, unchanged).
 */
export function shouldImmediateApplyConfigPath(path: string): boolean {
  const root = String(path || "").split(".")[0]?.trim();
  return Boolean(root) && IMMEDIATE_APPLY_ROOTS.has(root);
}

/**
 * Build the PUT /api/config/apply body from draft editor state or an explicit override.
 * Prefer frozen baseline hash/baseConfig from editBaseline; never invent a hash.
 */
export function buildConfigApplyRequestPayload(options: {
  draftOverride?: ConfigApplyDraftOverride;
  draftConfig: PublicConfigShape | null | undefined;
  draftMeta: ConfigDraftMeta;
  applyBaseHash: string;
  applyBaseConfig: PublicConfigShape | null | undefined;
  editorText: string;
  hasEditorChanges: boolean;
  editorSections: ConfigEditorSection[];
  loadFailedMessage: string;
}): ConfigApplyRequestPayload {
  const {
    draftOverride,
    draftConfig,
    draftMeta,
    applyBaseHash,
    applyBaseConfig,
    editorText,
    hasEditorChanges,
    editorSections,
    loadFailedMessage,
  } = options;

  if (draftOverride) {
    return {
      publicConfig: draftOverride.publicConfig,
      draftMeta: draftOverride.draftMeta,
      // Prefer frozen baseline hash; draftOverride.baseHash must not be the draft content hash.
      baseHash: applyBaseHash || draftOverride.baseHash,
      baseConfig: applyBaseConfig ?? null,
    };
  }

  if (applyBaseConfig) {
    return buildConfigApplyPayload({
      draftConfig: draftConfig ?? null,
      draftMeta,
      baseHash: applyBaseHash,
      baseConfig: applyBaseConfig ?? null,
      editorText,
      hasEditorChanges,
      editorSections,
      loadFailedMessage,
    });
  }

  // Snapshot apply: server checks baseHash against disk and replaces with full draft.
  return {
    publicConfig: buildConfigApplyPayload({
      draftConfig: draftConfig ?? null,
      draftMeta,
      baseHash: applyBaseHash,
      baseConfig: draftConfig ?? null,
      editorText,
      hasEditorChanges,
      editorSections,
      loadFailedMessage,
    }).publicConfig,
    draftMeta,
    baseHash: applyBaseHash,
    baseConfig: null,
  };
}
