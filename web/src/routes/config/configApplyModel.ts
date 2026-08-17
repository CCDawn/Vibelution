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

/** Appearance/profile section paths persist on save; routing and tooling still wait for explicit apply. */
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
