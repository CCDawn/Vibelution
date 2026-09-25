/**
 * Settings-align wave 3 — ConfigSectionEditor tree renderer, extracted
 * verbatim from ConfigRoute.tsx (zero behavior/style changes). Owns the
 * field kind matrix rendering, progressive disclosure tiers, section
 * save/cancel flow, avatar crop, and theme background controls.
 */

import { ChevronRight, Image as ImageIcon, Pencil, RotateCcw, Save, Upload, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";

import type { ConfigEditorMeta, ConfigEditorSection } from "../../api/types";
import { notifySettingsContentReady } from "../../app/settingsNavigation";
import {
  VButton,
  VCheckbox,
  VChip,
  VErrorSummary,
  VInput,
  VSettingsGroupCard,
  VSettingsRow,
  VStatusChip,
  VStringSelect,
  VSurface,
  VTextarea,
} from "../../components/vui";
import styles from "../ConfigRoute.styles";
import {
  avatarCropSourceRect,
  clampAvatarCropOffset,
  clonePublicConfig,
  getString,
  setValueAtConfigPath,
} from "../configRouteLogic";
import {
  configSectionFieldCopy,
  configSectionPresentation,
  configSectionTierCounts,
  isCommonConfigSectionEntry,
} from "../configSectionPresentation";
import { shouldImmediateApplyFieldKind, type ImmediateFieldStatus } from "./configApplyModel";
import type { ConfigCopy, ConfigLanguage } from "./configCopy";
import {
  collectPendingDraftLeaves,
  deriveNumberStep,
  fieldEditorDisplayText,
  isToolNameListPath,
  numberBounds,
  resolveDraftSubtreeForSave,
  stepNumberValue,
  validateJsonText,
  validateListText,
  validateNumberText,
} from "./configFieldEditorsModel";
import {
  configHint,
  configLabel,
  describeJsonIssue,
  describeListIssue,
  describeNumberIssue,
  formatConfigDisplayValue,
  isConfigObjectListValue,
  isPlainObject,
  readableErrorMessage,
  type ConfigSectionUiState,
} from "./configEditorModel";
type ConfigSectionEditorProps = {
  section: ConfigEditorSection;
  value: unknown;
  metaMap: Record<string, ConfigEditorMeta>;
  lang: ConfigLanguage;
  copy: ConfigCopy;
  disabled: boolean;
  uiState: ConfigSectionUiState;
  onUiStateChange: (sectionId: string, nextState: ConfigSectionUiState) => void;
  onSaveSection: (path: string, nextValue: unknown) => Promise<boolean>;
  onImmediateFieldChange: (path: string, nextValue: unknown) => void;
  immediateFieldStatus: Record<string, ImmediateFieldStatus>;
  onAvatarImageUpload: (file: File) => Promise<AvatarImageUploadResponse | null>;
  onThemeBackgroundImageUpload: (file: File) => Promise<AvatarImageUploadResponse | null>;
  /** 搜索深链的瞬态高亮字段（绝对配置路径）；仅该路径的行渲染高亮环。 */
  highlightFieldPath?: string;
  /** 分区保存失败的行内错误（wave 4）：落在该分区头部，不进全局 notice strip。 */
  saveError?: string;
};

export type AvatarImageUploadResponse = {
  path: string;
  url: string;
  contentType: string;
  sizeBytes: number;
};

type AvatarCropDraft = {
  absolutePath: string;
  fileName: string;
  objectUrl: string;
  imageWidth: number;
  imageHeight: number;
  zoom: number;
  offsetX: number;
  offsetY: number;
};

type AvatarCropDrag = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startOffsetX: number;
  startOffsetY: number;
};

const AVATAR_CROP_FRAME_SIZE = 320;
const AVATAR_CROP_PREVIEW_SIZE = 112;
const AVATAR_CROP_OUTPUT_SIZE = 512;

function avatarImagePreviewUrl(value: unknown): string {
  const path = getString(value).replace(/\\/g, "/").trim();
  const prefix = "workspace/user_avatars/";
  if (!path.startsWith(prefix)) {
    return "";
  }
  const filename = path.slice(prefix.length);
  if (!/^[A-Za-z0-9_.-]+$/.test(filename)) {
    return "";
  }
  return `/api/config/avatar-image/${encodeURIComponent(filename)}`;
}

function avatarImageDisplayName(value: unknown, copy: ConfigCopy): string {
  const path = getString(value).replace(/\\/g, "/").trim();
  if (!path) {
    return copy.avatarImageEmpty;
  }
  return path.split("/").filter(Boolean).at(-1) ?? path;
}

function themeBackgroundImagePreviewUrl(value: unknown): string {
  const path = getString(value).replace(/\\/g, "/").trim();
  const prefix = "theme_backgrounds/";
  if (!path.startsWith(prefix)) {
    return "";
  }
  const filename = path.slice(prefix.length);
  if (!/^[A-Za-z0-9_.-]+$/.test(filename)) {
    return "";
  }
  return `/api/config/theme-background-image/${encodeURIComponent(filename)}`;
}

function configEditorFieldKind(meta: ConfigEditorMeta | undefined): ConfigEditorMeta["kind"] | "background_image" {
  return (meta?.kind ?? "text") as ConfigEditorMeta["kind"] | "background_image";
}

function isDenseConfigSection(section: ConfigEditorSection): boolean {
  return Number(section.fieldCount || 0) >= 12;
}

export function ConfigSectionEditor({
  section,
  value,
  metaMap,
  lang,
  copy,
  disabled,
  uiState,
  onUiStateChange,
  onSaveSection,
  onImmediateFieldChange,
  immediateFieldStatus,
  onAvatarImageUpload,
  onThemeBackgroundImageUpload,
  highlightFieldPath = "",
  saveError = "",
}: ConfigSectionEditorProps) {
  const sectionExpanded = uiState.expanded;
  const editing = uiState.editing;
  const advancedExpanded = uiState.advancedExpanded;
  const expandedPaths = uiState.expandedPaths;
  const presentation = configSectionPresentation(section.id, lang);
  const tierCounts = configSectionTierCounts(section.id, section.fieldCount);
  const draftValue = editing ? (uiState.draftValue ?? value) : value;
  const metaAt = useCallback((path: string) => metaMap[path], [metaMap]);
  // 内容 ready 脉冲：挂载与行可见性（分区展开/高级展开/嵌套展开）变化后经
  // 意图模块广播；导航意图（分区/字段聚焦）据此落地，替代旧的 60 帧 rAF 轮询。
  useEffect(() => {
    notifySettingsContentReady();
  }, [section.id, sectionExpanded, advancedExpanded, expandedPaths]);
  // 待保存口径：草稿类字段的草稿值（原始文本先按 schema 解析）与当前分区值比较；
  // 即时类字段（boolean/select）永不滞留草稿，不计入。
  const pendingDraftLeaves = useMemo(
    () => (editing
      ? collectPendingDraftLeaves({ draft: draftValue, committed: value, path: section.path, metaAt })
      : []),
    [editing, draftValue, value, section.path, metaAt],
  );
  const sectionSaveBlocked = pendingDraftLeaves.some((leaf) => !leaf.valid);
  const sectionClassName = [
    styles.sectionSurface,
    styles.configEditorSection,
    isDenseConfigSection(section) && !presentation ? styles.configDenseSection : "",
  ].filter(Boolean).join(" ");
  const [uploadingImagePath, setUploadingImagePath] = useState("");
  const [avatarCrop, setAvatarCrop] = useState<AvatarCropDraft | null>(null);
  const [avatarCropError, setAvatarCropError] = useState("");
  const avatarCropDragRef = useRef<AvatarCropDrag | null>(null);

  useEffect(() => {
    const objectUrl = avatarCrop?.objectUrl;
    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [avatarCrop?.objectUrl]);

  function updateSectionDraft(absolutePath: string, nextValue: unknown) {
    const prefix = `${section.path}.`;
    const relativePath = absolutePath === section.path ? "" : absolutePath.startsWith(prefix) ? absolutePath.slice(prefix.length) : absolutePath;
    const currentDraft = editing ? draftValue : value;
    onUiStateChange(section.id, {
      ...uiState,
      editing: true,
      expanded: true,
      draftValue: setValueAtConfigPath(currentDraft, relativePath, nextValue),
    });
  }

  function toggleObjectPath(path: string) {
    onUiStateChange(section.id, {
      ...uiState,
      expandedPaths: { ...expandedPaths, [path]: !expandedPaths[path] },
    });
  }

  function clampAvatarCrop(next: AvatarCropDraft): AvatarCropDraft {
    const offset = clampAvatarCropOffset({
      imageWidth: next.imageWidth,
      imageHeight: next.imageHeight,
      frameSize: AVATAR_CROP_FRAME_SIZE,
      zoom: next.zoom,
      offsetX: next.offsetX,
      offsetY: next.offsetY,
    });
    return { ...next, ...offset };
  }

  async function beginAvatarCrop(file: File, absolutePath: string) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      throw new Error(copy.avatarTypeError);
    }
    const image = await loadImageForCrop(file, copy);
    setAvatarCropError("");
    setAvatarCrop((current) => {
      if (current?.objectUrl) {
        URL.revokeObjectURL(current.objectUrl);
      }
      return clampAvatarCrop({
        absolutePath,
        fileName: file.name,
        objectUrl: image.objectUrl,
        imageWidth: image.width,
        imageHeight: image.height,
        zoom: 1,
        offsetX: 0,
        offsetY: 0,
      });
    });
  }

  async function confirmAvatarCrop() {
    if (!avatarCrop) {
      return;
    }
    setUploadingImagePath(avatarCrop.absolutePath);
    try {
      const croppedFile = await createCroppedAvatarFile(avatarCrop, copy);
      const result = await onAvatarImageUpload(croppedFile);
      if (result?.path) {
        updateSectionDraft(avatarCrop.absolutePath, result.path);
        setAvatarCrop(null);
      }
    } catch (error) {
      setAvatarCropError(readableErrorMessage(error));
    } finally {
      setUploadingImagePath("");
    }
  }

  function cancelAvatarCrop() {
    setAvatarCropError("");
    setAvatarCrop(null);
  }

  async function handleSave() {
    // 非法草稿阻塞分区保存（不再静默存原始串）：先整树解析，非法即拒绝。
    if (sectionSaveBlocked) {
      return;
    }
    const resolution = resolveDraftSubtreeForSave({ draft: draftValue, path: section.path, metaAt });
    if (!resolution.ok) {
      return;
    }
    const ok = await onSaveSection(section.path, resolution.value);
    if (ok) {
      onUiStateChange(section.id, {
        ...uiState,
        editing: false,
        draftValue: undefined,
      });
    }
  }

  async function uploadThemeBackgroundFile(file: File, absolutePath: string) {
    setUploadingImagePath(absolutePath);
    try {
      const uploaded = await onThemeBackgroundImageUpload(file);
      if (uploaded) {
        updateSectionDraft(absolutePath, uploaded.path);
      }
    } finally {
      setUploadingImagePath("");
    }
  }

  function themeBackgroundDisplayName(value: unknown): string {
    const path = getString(value).replace(/\\/g, "/").trim();
    if (!path) {
      return copy.emptyValue;
    }
    return path.split("/").filter(Boolean).at(-1) ?? path;
  }

  function renderThemeBackgroundControl(fieldValue: unknown, absolutePath: string) {
    const previewUrl = themeBackgroundImagePreviewUrl(fieldValue);
    const imageUploading = uploadingImagePath === absolutePath;
    const currentPath = getString(fieldValue).replace(/\\/g, "/").trim();
    const presetOptions = metaMap[absolutePath]?.options ?? [];
    return (
      <div className={styles.themeBackgroundImageEditor}>
        <div className={styles.themeBackgroundImageValue}>
          <label
            className={styles.themeBackgroundDropButton}
            title={copy.uploadThemeBackgroundImage}
            aria-label={copy.uploadThemeBackgroundImage}
          >
            {previewUrl ? (
              <img src={previewUrl} alt="" className={styles.themeBackgroundImagePreview} />
            ) : (
              <span className={styles.themeBackgroundImagePlaceholder}>
                <ImageIcon size={16} />
              </span>
            )}
            <VInput
              type="file"
              accept="image/png,image/jpeg,image/webp"
              disabled={disabled || imageUploading}
              onChange={async (event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                if (!file) {
                  return;
                }
                await uploadThemeBackgroundFile(file, absolutePath);
              }}
            />
          </label>
          <div className={styles.themeBackgroundImageMeta}>
            <strong>{configLabel(metaMap, absolutePath, lang)}</strong>
            <span>{themeBackgroundDisplayName(fieldValue)}</span>
            <div className={styles.themeBackgroundImageActions}>
              <label className={`${styles.actionButton} ${styles.compactButton} ${styles.fileUploadButton}`}>
                <Upload size={14} />
                {imageUploading ? copy.themeBackgroundImageUploading : copy.uploadThemeBackgroundImage}
                <VInput
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  disabled={disabled || imageUploading}
                  onChange={async (event) => {
                    const file = event.currentTarget.files?.[0];
                    event.currentTarget.value = "";
                    if (!file) {
                      return;
                    }
                    await uploadThemeBackgroundFile(file, absolutePath);
                  }}
                />
              </label>
              {getString(fieldValue) ? (
                <VButton
                  type="button"
                  className={`${styles.actionButton} ${styles.compactButton}`}
                  isDisabled={disabled || imageUploading}
                  onClick={() => updateSectionDraft(absolutePath, "")}
 icon={<X size={14} />}>
                    {copy.clearThemeBackgroundImage}
                  </VButton>
              ) : null}
            </div>
          </div>
        </div>
        {presetOptions.length ? (
          <div className={styles.themeBackgroundPresetPanel} aria-label={copy.themeBackgroundPresetTitle}>
            <span className={styles.themeBackgroundPresetTitle}>{copy.themeBackgroundPresetTitle}</span>
            <div className={styles.themeBackgroundPresetGrid}>
              {presetOptions.map((option) => {
                const optionPreviewUrl = themeBackgroundImagePreviewUrl(option.value);
                const active = currentPath === option.value;
                return (
                  <VButton
                    key={option.value}
                    type="button"
                    contentLayout="plain"
                    className={styles.themeBackgroundPresetButton}
                    data-active={active ? "true" : undefined}
                    isDisabled={disabled || imageUploading}
                    aria-pressed={active}
                    title={option.label}
                    onClick={() => updateSectionDraft(absolutePath, option.value)}
                  >
                    {optionPreviewUrl ? <img src={optionPreviewUrl} alt="" /> : <ImageIcon size={14} />}
                    <span>{option.label}</span>
                    {active ? <em>{copy.currentBadge}</em> : null}
                  </VButton>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  function renderRowStatusBadge(absolutePath: string, options: { pending?: boolean; invalid?: boolean } = {}) {
    const immediateStatus = immediateFieldStatus[absolutePath];
    if (immediateStatus === "waiting") {
      return (
        <VChip tone="info" data-testid={`row-status-${absolutePath}`} data-vui-row-status="waiting">
          {copy.rowStatusWaiting}
        </VChip>
      );
    }
    if (immediateStatus === "applied") {
      return (
        <VChip tone="accent" data-testid={`row-status-${absolutePath}`} data-vui-row-status="applied">
          {copy.rowStatusApplied}
        </VChip>
      );
    }
    if (immediateStatus === "failed") {
      return (
        <VChip tone="danger" data-testid={`row-status-${absolutePath}`} data-vui-row-status="failed">
          {copy.rowStatusFailed}
        </VChip>
      );
    }
    if (options.pending) {
      return (
        <VChip
          tone={options.invalid ? "danger" : "neutral"}
          data-testid={`row-status-${absolutePath}`}
          data-vui-row-status={options.invalid ? "invalid" : "pending"}
        >
          {copy.rowStatusPending}
        </VChip>
      );
    }
    return null;
  }

  function renderFieldView(fieldValue: unknown, absolutePath: string) {
    const meta = metaMap[absolutePath];
    const kind = configEditorFieldKind(meta);
    if (kind === "background_image") {
      const hint = configHint(metaMap, absolutePath, lang);
      return (
        <article
          key={absolutePath}
          className={`${styles.treeFieldCard} ${styles.themeBackgroundImageCard}`}
          title={hint || undefined}
        >
          {renderThemeBackgroundControl(fieldValue, absolutePath)}
        </article>
      );
    }
    if (kind === "image") {
      const previewUrl = avatarImagePreviewUrl(fieldValue);
      const displayName = avatarImageDisplayName(fieldValue, copy);
      return (
        <article
          key={absolutePath}
          className={`${styles.treeFieldCard} ${styles.treeFieldCardView} ${styles.avatarImageCard}`}
        >
          <div className={styles.treeFieldHead}>
            <span className={styles.treeFieldLabel}>{configLabel(metaMap, absolutePath, lang)}</span>
          </div>
          {configHint(metaMap, absolutePath, lang) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath, lang)}</p> : null}
          <div className={styles.avatarImageValue}>
            {previewUrl ? (
              <img src={previewUrl} alt="" className={styles.avatarImagePreview} />
            ) : (
              <span className={styles.avatarImagePlaceholder}>
                <ImageIcon size={16} />
              </span>
            )}
            <div className={styles.avatarImageMeta}>
              <strong>{previewUrl ? copy.avatarImageCurrent : copy.avatarImageEmpty}</strong>
              <span>{displayName}</span>
            </div>
          </div>
        </article>
      );
    }
    const label = configLabel(metaMap, absolutePath, lang);
    const hint = configHint(metaMap, absolutePath, lang);
    // 即时类字段（布尔/下拉）在查看态行内直接可改：改动即走保存+apply。
    const immediate = shouldImmediateApplyFieldKind(meta?.kind);
    let control: ReactNode;
    if (kind === "boolean") {
      control = (
        <VCheckbox
          className={styles.toggleField}
          isSelected={Boolean(fieldValue)}
          isDisabled={disabled}
          aria-label={label}
          onChange={(isSelected) => onImmediateFieldChange(absolutePath, isSelected)}
        />
      );
    } else if (kind === "select") {
      control = (
        <VStringSelect
          ariaLabel={label}
          isDisabled={disabled}
          value={getString(fieldValue)}
          options={(meta?.options ?? []).map((option) => ({
            value: option.value,
            label: option.label,
          }))}
          onValueChange={(nextValue) => onImmediateFieldChange(absolutePath, nextValue)}
        />
      );
    } else {
      control = (
        <span className={styles.settingsRowReadonlyValue} data-testid={`value-${absolutePath}`}>
          {formatConfigDisplayValue(fieldValue, meta?.kind, copy)}
        </span>
      );
    }
    return (
      <VSettingsRow
        key={absolutePath}
        testId={`row-${absolutePath}`}
        label={label}
        description={hint || undefined}
        control={control}
        status={renderRowStatusBadge(absolutePath)}
        highlighted={highlightFieldPath === absolutePath}
      />
    );
  }

  function renderFieldEditor(fieldValue: unknown, absolutePath: string) {
    const meta = metaMap[absolutePath];
    const kind = configEditorFieldKind(meta);
    const imageUploading = uploadingImagePath === absolutePath;

    if (kind === "background_image") {
      const backgroundHint = configHint(metaMap, absolutePath, lang);
      return (
        <article
          key={absolutePath}
          className={`${styles.treeFieldCard} ${styles.themeBackgroundImageCard}`}
          title={backgroundHint || undefined}
        >
          {renderThemeBackgroundControl(fieldValue, absolutePath)}
        </article>
      );
    }
    if (kind === "image") {
      const previewUrl = avatarImagePreviewUrl(fieldValue);
      const displayName = avatarImageDisplayName(fieldValue, copy);
      const cropDraft = avatarCrop?.absolutePath === absolutePath ? avatarCrop : null;
      const cropScale = cropDraft
        ? (AVATAR_CROP_FRAME_SIZE / Math.min(cropDraft.imageWidth, cropDraft.imageHeight)) * cropDraft.zoom
        : 1;
      const cropImageStyle: CSSProperties | undefined = cropDraft
        ? {
            width: cropDraft.imageWidth * cropScale,
            height: cropDraft.imageHeight * cropScale,
            transform: `translate(calc(-50% + ${cropDraft.offsetX}px), calc(-50% + ${cropDraft.offsetY}px))`,
          }
        : undefined;
      const cropPreviewRatio = AVATAR_CROP_PREVIEW_SIZE / AVATAR_CROP_FRAME_SIZE;
      const cropPreviewImageStyle: CSSProperties | undefined = cropDraft
        ? {
            width: cropDraft.imageWidth * cropScale * cropPreviewRatio,
            height: cropDraft.imageHeight * cropScale * cropPreviewRatio,
            transform: `translate(calc(-50% + ${cropDraft.offsetX * cropPreviewRatio}px), calc(-50% + ${cropDraft.offsetY * cropPreviewRatio}px))`,
          }
        : undefined;
      const control = (
        <div className={styles.avatarImageEditor}>
          <div className={styles.avatarImageValue}>
            <label
              className={styles.avatarImageDropButton}
              title={copy.avatarImageClickToUpload}
              aria-label={copy.avatarImageClickToUpload}
            >
              {previewUrl ? (
                <img src={previewUrl} alt="" className={styles.avatarImagePreview} />
              ) : (
                <span className={styles.avatarImagePlaceholder}>
                  <ImageIcon size={16} />
                </span>
              )}
              <span className={styles.avatarImageUploadCue}>
                <Upload size={12} />
              </span>
              <VInput
                type="file"
                accept="image/png,image/jpeg,image/webp"
                disabled={disabled || imageUploading}
                onChange={async (event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (!file) {
                    return;
                  }
                  try {
                    await beginAvatarCrop(file, absolutePath);
                  } catch (error) {
                    setAvatarCropError(readableErrorMessage(error));
                  } finally {
                    setUploadingImagePath("");
                  }
                }}
              />
            </label>
            <div className={styles.avatarImageMeta}>
              <strong>{configLabel(metaMap, absolutePath, lang)}</strong>
              <span>{displayName}</span>
            </div>
          </div>
          {cropDraft ? (
            <div className={styles.avatarCropPanel}>
              <div className={styles.avatarCropHeader}>
                <div>
                  <strong>{copy.avatarCropTitle}</strong>
                  <p>{copy.avatarCropHint}</p>
                </div>
                <span>{copy.avatarCropPreview}</span>
              </div>
              <div className={styles.avatarCropWorkspace}>
                <div
                  className={styles.avatarCropFrame}
                  onPointerDown={(event) => {
                    event.currentTarget.setPointerCapture(event.pointerId);
                    avatarCropDragRef.current = {
                      pointerId: event.pointerId,
                      startClientX: event.clientX,
                      startClientY: event.clientY,
                      startOffsetX: cropDraft.offsetX,
                      startOffsetY: cropDraft.offsetY,
                    };
                  }}
                  onPointerMove={(event) => {
                    const drag = avatarCropDragRef.current;
                    if (!drag || drag.pointerId !== event.pointerId) {
                      return;
                    }
                    const next = clampAvatarCrop({
                      ...cropDraft,
                      offsetX: drag.startOffsetX + event.clientX - drag.startClientX,
                      offsetY: drag.startOffsetY + event.clientY - drag.startClientY,
                    });
                    setAvatarCrop(next);
                  }}
                  onPointerUp={(event) => {
                    if (avatarCropDragRef.current?.pointerId === event.pointerId) {
                      avatarCropDragRef.current = null;
                    }
                  }}
                  onPointerCancel={() => {
                    avatarCropDragRef.current = null;
                  }}
                >
                  <img src={cropDraft.objectUrl} alt="" className={styles.avatarCropImage} style={cropImageStyle} draggable={false} />
                  <span className={styles.avatarCropMask} />
                </div>
                <div className={styles.avatarCropPreviewWrap}>
                  <div className={styles.avatarCropPreview}>
                    <img src={cropDraft.objectUrl} alt="" className={styles.avatarCropImage} style={cropPreviewImageStyle} draggable={false} />
                  </div>
                </div>
              </div>
              <label className={styles.avatarCropZoomField}>
                <span>{copy.avatarCropZoom}</span>
                <VInput
                  type="range"
                  min="1"
                  max="3"
                  step="0.01"
                  value={cropDraft.zoom}
                  onChange={(event) => {
                    const zoom = Number(event.target.value);
                    setAvatarCrop(clampAvatarCrop({ ...cropDraft, zoom }));
                  }}
                />
              </label>
              <div className={styles.avatarImageActions}>
                <VButton
                  type="button"
                  variant="primary"
                  className={`${styles.primaryButton} ${styles.compactButton}`}
                  isDisabled={disabled || imageUploading}
                  onClick={() => {
                    void confirmAvatarCrop();
                  }}

                    icon={<Save size={14} />}
                  >
                    {imageUploading ? copy.avatarImageUploading : copy.avatarCropConfirm}
                  </VButton>
                <VButton
                  type="button"
                  className={`${styles.actionButton} ${styles.compactButton}`}
                  isDisabled={disabled || imageUploading}
                  onClick={cancelAvatarCrop}
 icon={<X size={14} />}>
                  {copy.avatarCropCancel}
                </VButton>
              </div>
            </div>
          ) : null}
          <div className={styles.avatarImageActions}>
            <label className={`${styles.actionButton} ${styles.compactButton} ${styles.fileUploadButton}`}>
              <Upload size={14} />
              {cropDraft ? copy.uploadAvatarImage : imageUploading ? copy.avatarImageUploading : copy.uploadAvatarImage}
              <VInput
                type="file"
                accept="image/png,image/jpeg,image/webp"
                disabled={disabled || imageUploading}
                onChange={async (event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (!file) {
                    return;
                  }
                  try {
                    await beginAvatarCrop(file, absolutePath);
                  } catch (error) {
                    setAvatarCropError(readableErrorMessage(error));
                  } finally {
                    setUploadingImagePath("");
                  }
                }}
              />
            </label>
            {getString(fieldValue) ? (
              <VButton
                type="button"
                className={`${styles.actionButton} ${styles.compactButton}`}
                isDisabled={disabled || imageUploading}
                onClick={() => updateSectionDraft(absolutePath, "")}
 icon={<X size={14} />}>
                  {copy.clearAvatarImage}
                </VButton>
            ) : null}
          </div>
          {avatarCropError ? <p className={styles.inlineError}>{avatarCropError}</p> : null}
        </div>
      );
      return (
        <article key={absolutePath} className={`${styles.treeFieldCard} ${styles.treeFieldCardEdit} ${styles.avatarImageCard}`}>
          {control}
        </article>
      );
    }
    const label = configLabel(metaMap, absolutePath, lang);
    const hint = configHint(metaMap, absolutePath, lang);
    // 即时类字段在编辑态也直接生效（与查看态同一声明），不会滞留草稿。
    const pendingLeaf = pendingDraftLeaves.find((leaf) => leaf.path === absolutePath);
    const pendingFlag = Boolean(pendingLeaf);
    const invalidFlag = pendingLeaf ? !pendingLeaf.valid : false;
    let control: ReactNode;
    let detail: ReactNode;
    let footer: ReactNode;
    let controlLayout: "default" | "wide" = "default";

    if (kind === "boolean") {
      control = (
        <VCheckbox
          className={styles.toggleField}
          isSelected={Boolean(fieldValue)}
          isDisabled={disabled}
          aria-label={label}
          onChange={(isSelected) => onImmediateFieldChange(absolutePath, isSelected)}
        />
      );
    } else if (kind === "select") {
      control = (
        <VStringSelect
          ariaLabel={label}
          isDisabled={disabled}
          value={getString(fieldValue)}
          options={(meta?.options ?? []).map((option) => ({
            value: option.value,
            label: option.label,
          }))}
          onValueChange={(nextValue) => onImmediateFieldChange(absolutePath, nextValue)}
        />
      );
    } else if (kind === "number") {
      // number：步进器 + schema min/max 硬校验 + 单位后缀（schema 无范围则不造范围）。
      const bounds = numberBounds(meta);
      const step = deriveNumberStep(meta, typeof fieldValue === "number" ? fieldValue : undefined);
      const rawText = fieldEditorDisplayText("number", fieldValue, fieldValue);
      const numberResult = validateNumberText(rawText, bounds);
      const rangeParts = [
        bounds.min ? `${bounds.min.exclusive ? "(" : "["}${bounds.min.value}` : null,
        bounds.max ? `${bounds.max.value}${bounds.max.exclusive ? ")" : "]"}` : null,
      ].filter(Boolean);
      controlLayout = "wide";
      control = (
        <div className={styles.numberStepper} data-testid={`number-editor-${absolutePath}`}>
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            contentLayout="plain"
            aria-label="-"
            data-testid={`step-down-${absolutePath}`}
            isDisabled={disabled || !numberResult.ok}
            onClick={() => {
              const current = numberResult.ok ? numberResult.value : 0;
              updateSectionDraft(absolutePath, String(stepNumberValue(current, bounds, -1, step)));
            }}
          >
            −
          </VButton>
          <VInput
            type="text"
            inputMode="decimal"
            value={rawText}
            aria-label={label}
            aria-invalid={numberResult.ok ? undefined : true}
            className={`${styles.numberStepperInput} ${numberResult.ok ? "" : styles.numberStepperInputInvalid}`}
            onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
          />
          <VButton
            type="button"
            variant="secondary"
            density="compact"
            contentLayout="plain"
            aria-label="+"
            data-testid={`step-up-${absolutePath}`}
            isDisabled={disabled || !numberResult.ok}
            onClick={() => {
              const current = numberResult.ok ? numberResult.value : (bounds.min?.value ?? 0);
              updateSectionDraft(absolutePath, String(stepNumberValue(current, bounds, 1, step)));
            }}
          >
            +
          </VButton>
          {meta?.unit ? <span className={styles.numberStepperUnit}>{meta.unit}</span> : null}
        </div>
      );
      detail = (
        <div className={styles.numberStepperMeta}>
          {rangeParts.length ? (
            <span className={styles.numberStepperHint}>
              {copy.numberRangeHint} {rangeParts.join(" ~ ")} · {copy.numberStepHint} ±{step}
            </span>
          ) : null}
          {!numberResult.ok ? (
            <span className={styles.numberStepperError} data-testid={`number-error-${absolutePath}`}>
              {describeNumberIssue(numberResult.issue, copy)}
            </span>
          ) : null}
        </div>
      );
    } else if (kind === "string_list") {
      // list：textarea 逐行校验。工具名单类=注册名格式+去重（错误，阻塞保存）；
      // 通用列表=空行/首尾空格自动清理提示（warning，不阻塞）。
      const rawText = fieldEditorDisplayText("string_list", fieldValue, fieldValue);
      const listResult = validateListText(rawText, { toolNames: isToolNameListPath(absolutePath) });
      const listErrors = listResult.issues.filter((issue) => issue.severity === "error");
      const listWarnings = listResult.issues.filter((issue) => issue.severity === "warning");
      const warningMessages = [...new Set(listWarnings.map((issue) => describeListIssue(issue, copy)))];
      footer = (
        <div className={styles.settingsRowFooter}>
          <VTextarea
            minRows={Math.max(4, rawText.split(/\r?\n/).length + 1)}
            value={rawText}
            aria-label={label}
            aria-invalid={listErrors.length > 0 ? true : undefined}
            // vuiFormControlClass 自带固定高度类；多行编辑器按 rows 自然撑高。
            style={{ height: "auto" }}
            className={`${styles.settingsWideTextarea} ${listErrors.length > 0 ? styles.settingsWideTextareaInvalid : ""}`}
            onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
          />
          {listErrors.length > 0 ? (
            <ul className={styles.settingsRowFooter} data-testid={`list-errors-${absolutePath}`}>
              {listErrors.map((issue, issueIndex) => (
                <li key={`${issue.line}-${issueIndex}`} className={styles.settingsRowIssueLine}>
                  {describeListIssue(issue, copy)}
                </li>
              ))}
            </ul>
          ) : null}
          {warningMessages.length > 0 ? (
            <p className={styles.settingsRowWarning}>{warningMessages.join(" ")}</p>
          ) : null}
        </div>
      );
    } else if (kind === "multiline") {
      control = (
        <VTextarea
          minRows={10}
          value={getString(fieldValue)}
          aria-label={label}
          onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
        />
      );
    } else if (kind === "json") {
      // json：实时校验。非法=红边+首个解析错误行列定位（阻塞保存），合法=弱提示。
      const rawText = fieldEditorDisplayText("json", fieldValue, fieldValue);
      const jsonResult = validateJsonText(rawText);
      footer = (
        <div className={styles.settingsRowFooter}>
          <VTextarea
            minRows={6}
            value={rawText}
            aria-label={label}
            aria-invalid={jsonResult.ok ? undefined : true}
            data-testid={`json-editor-${absolutePath}`}
            // vuiFormControlClass 自带固定高度类；宽编辑器按 rows 自然撑高。
            style={{ height: "auto" }}
            className={`${styles.settingsWideTextarea} ${jsonResult.ok ? "" : styles.settingsWideTextareaInvalid}`}
            onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
          />
          {jsonResult.ok ? (
            <p className={styles.settingsRowStatusLine} data-vui-json="valid">
              {copy.jsonValidHint}
            </p>
          ) : (
            <p className={styles.settingsRowStatusLineInvalid} data-vui-json="invalid" data-testid={`json-error-${absolutePath}`}>
              {describeJsonIssue(jsonResult.issue, copy)}
            </p>
          )}
        </div>
      );
    } else {
      control = (
        <VInput
          type={kind === "secret" ? "password" : "text"}
          value={getString(fieldValue)}
          aria-label={label}
          onChange={(event) => updateSectionDraft(absolutePath, event.target.value)}
        />
      );
    }

    return (
      <VSettingsRow
        key={absolutePath}
        testId={`row-${absolutePath}`}
        label={label}
        description={hint || undefined}
        control={control}
        detail={detail}
        footer={footer}
        controlLayout={controlLayout}
        status={renderRowStatusBadge(absolutePath, { pending: pendingFlag, invalid: invalidFlag })}
        highlighted={highlightFieldPath === absolutePath}
      />
    );
  }

  function renderNestedBlock(absolutePath: string, count: number, children: ReactNode, titleOverride?: string) {
    const expanded = Boolean(expandedPaths[absolutePath]);
    return (
      <div className={styles.treeObjectBlock}>
        <VButton
          type="button"
          contentLayout="plain"
          className={styles.treeToggle}
          aria-expanded={expanded}
          onClick={() => toggleObjectPath(absolutePath)}
        >
          <div className={styles.treeToggleLabel}>
            <ChevronRight size={14} className={expanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon} />
            <div>
              <p className={styles.cardTitle}>{titleOverride ?? configLabel(metaMap, absolutePath, lang)}</p>
              {configHint(metaMap, absolutePath, lang) ? <p className={styles.treeHint}>{configHint(metaMap, absolutePath, lang)}</p> : null}
            </div>
          </div>
          <VStatusChip tone="neutral">{count}</VStatusChip>
        </VButton>
        {expanded ? <div className={styles.treeBody}>{children}</div> : null}
      </div>
    );
  }

  function renderConfigField(childValue: unknown, childPath: string, mode: "view" | "edit") {
    return mode === "edit" ? renderFieldEditor(childValue, childPath) : renderFieldView(childValue, childPath);
  }

  function renderUserProfileBody(nodeValue: Record<string, unknown>, absolutePath: string, mode: "view" | "edit") {
    if (!presentation) {
      return null;
    }
    const field = (key: string) => renderConfigField(nodeValue[key], `${absolutePath}.${key}`, mode);
    return (
      <div className={styles.userProfileLayout}>
        <div className={styles.configTier}>
          <div className={styles.configTierHeader}>
            <div className={styles.configTierHeaderCopy}>
              <strong>{presentation.commonTitle}</strong>
              <span>{presentation.commonHint}</span>
            </div>
            <VStatusChip tone="neutral">{presentation.advancedCountLabel(tierCounts.common)}</VStatusChip>
          </div>
          <div className={styles.userProfilePrimaryGrid}>
            <VSettingsGroupCard className={styles.userProfileIdentityFields}>
              {field("display_name")}
            </VSettingsGroupCard>
            <div className={styles.userProfileAvatarGroup}>
              <div className={styles.userProfileAvatarHeader}>
                <strong>{copy.userProfileAvatarGroupTitle}</strong>
                <span>{copy.userProfileAvatarGroupHint}</span>
              </div>
              <VSettingsGroupCard className={styles.userProfileAvatarFields}>
                {field("avatar_preset")}
                {field("avatar_image_path")}
              </VSettingsGroupCard>
            </div>
          </div>
        </div>

        <div className={`${styles.configTier} ${styles.configAdvancedTier}`}>
          <VButton
            type="button"
            contentLayout="plain"
            className={styles.configAdvancedToggle}
            aria-expanded={advancedExpanded}
            onClick={() => {
              onUiStateChange(section.id, {
                ...uiState,
                advancedExpanded: !advancedExpanded,
              });
            }}
          >
            <div className={styles.configTierHeaderCopy}>
              <strong>{presentation.advancedTitle}</strong>
              <span>{presentation.advancedHint}</span>
            </div>
            <div className={styles.configAdvancedToggleMeta}>
              <VStatusChip tone="neutral">{presentation.advancedCountLabel(tierCounts.advanced)}</VStatusChip>
              <ChevronRight
                size={16}
                className={advancedExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon}
              />
            </div>
          </VButton>
          {advancedExpanded ? (
            <VSettingsGroupCard className={`${styles.configAdvancedBody} ${styles.userProfileAdvancedFields}`}>
              {field("bio")}
              {field("preferences")}
            </VSettingsGroupCard>
          ) : null}
        </div>
      </div>
    );
  }

  function renderObjectEntry(
    [key, childValue]: [string, unknown],
    absolutePath: string,
    mode: "view" | "edit",
  ) {
    const childPath = `${absolutePath}.${key}`;
    const childMetaKind = metaMap[childPath]?.kind;
    const childIsObjectList = isConfigObjectListValue(childValue, childMetaKind);
    const childIsObject = isPlainObject(childValue);
    if (childIsObject || childIsObjectList) {
      const childExpanded = Boolean(expandedPaths[childPath]);
      return (
        <div key={childPath} className={childExpanded ? styles.treeWide : styles.treeObjectCell}>
          {renderNode(childValue, childPath, mode)}
        </div>
      );
    }
    return renderConfigField(childValue, childPath, mode);
  }

  function renderObjectBody(nodeValue: Record<string, unknown>, absolutePath: string, mode: "view" | "edit") {
    const entries = Object.entries(nodeValue).filter(([key]) => {
      if (absolutePath !== section.path) return true;
      const childPath = `${absolutePath}.${key}`;
      return Boolean(metaMap[childPath]);
    });
    if (!entries.length) {
      return <p className={styles.helperText}>{copy.emptyValue}</p>;
    }
    if (absolutePath === "user_profile") {
      return renderUserProfileBody(nodeValue, absolutePath, mode);
    }
    if (absolutePath === section.path && presentation) {
      const commonEntries = entries.filter(([key]) => {
        const childPath = `${absolutePath}.${key}`;
        return isCommonConfigSectionEntry(section.id, childPath);
      });
      const advancedEntries = entries.filter(([key]) => {
        const childPath = `${absolutePath}.${key}`;
        return !isCommonConfigSectionEntry(section.id, childPath);
      });
      return (
        <div
          className={`${styles.configProgressiveBody} ${
            presentation.layout === "compact_paths" ? styles.configCompactPathProgressiveBody : ""
          } ${presentation.layout === "compact_paths" && advancedEntries.length > 0 ? styles.configCompactAdvancedProgressiveBody : ""}`}
        >
          <div className={styles.configTier}>
            <div className={styles.configTierHeader}>
              <div className={styles.configTierHeaderCopy}>
                <strong>{presentation.commonTitle}</strong>
                <span>{presentation.commonHint}</span>
              </div>
              <VStatusChip tone="neutral">{presentation.advancedCountLabel(tierCounts.common)}</VStatusChip>
            </div>
            <VSettingsGroupCard
              testId={`settings-group-${absolutePath}`}
              className={styles.treeGrid}
            >
              {commonEntries.map((entry) => renderObjectEntry(entry, absolutePath, mode))}
            </VSettingsGroupCard>
          </div>

          {advancedEntries.length > 0 ? (
            <div className={`${styles.configTier} ${styles.configAdvancedTier}`}>
              <VButton
                type="button"
                contentLayout="plain"
                className={styles.configAdvancedToggle}
                aria-expanded={advancedExpanded}
                onClick={() => {
                  onUiStateChange(section.id, {
                    ...uiState,
                    advancedExpanded: !advancedExpanded,
                  });
                }}
              >
                <div className={styles.configTierHeaderCopy}>
                  <strong>{presentation.advancedTitle}</strong>
                  <span>{presentation.advancedHint}</span>
                </div>
                <div className={styles.configAdvancedToggleMeta}>
                  <VStatusChip tone="neutral">{presentation.advancedCountLabel(tierCounts.advanced)}</VStatusChip>
                  <ChevronRight
                    size={16}
                    className={advancedExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon}
                  />
                </div>
              </VButton>
              {advancedExpanded ? (
                <div className={styles.configAdvancedBody}>
                  <VSettingsGroupCard className={`${styles.treeGrid} ${styles.configAdvancedGrid}`}>
                    {advancedEntries.map((entry) => renderObjectEntry(entry, absolutePath, mode))}
                  </VSettingsGroupCard>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      );
    }
    return (
      <VSettingsGroupCard
        testId={`settings-group-${absolutePath}`}
        className={styles.treeGrid}
      >
        {entries.map((entry) => renderObjectEntry(entry, absolutePath, mode))}
      </VSettingsGroupCard>
    );
  }

  function renderNode(nodeValue: unknown, absolutePath: string, mode: "view" | "edit", itemIndex?: number) {
    const isRoot = absolutePath === section.path;
    if (isConfigObjectListValue(nodeValue, metaMap[absolutePath]?.kind)) {
      if (isRoot) {
        return nodeValue.length ? (
          <div className={styles.treeStack}>
            {nodeValue.map((item, index) => (
              <div key={`${absolutePath}.${index}`} className={styles.treeNestedBlock}>
                <div className={styles.treeNestedHeader}>
                  <strong>{`${copy.itemLabel} ${index + 1}`}</strong>
                </div>
                {renderObjectBody(item as Record<string, unknown>, `${absolutePath}.${index}`, mode)}
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.helperText}>{copy.emptyValue}</p>
        );
      }

      return renderNestedBlock(
        absolutePath,
        nodeValue.length,
        nodeValue.length ? (
          <div className={styles.treeStack}>
            {nodeValue.map((item, index) => (
              <div key={`${absolutePath}.${index}`} className={styles.treeNestedBlock}>
                <div className={styles.treeNestedHeader}>
                  <strong>{`${copy.itemLabel} ${index + 1}`}</strong>
                </div>
                {renderObjectBody(item as Record<string, unknown>, `${absolutePath}.${index}`, mode)}
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.helperText}>{copy.emptyValue}</p>
        ),
      );
    }

    if (isPlainObject(nodeValue)) {
      if (isRoot) {
        return renderObjectBody(nodeValue, absolutePath, mode);
      }
      const label = itemIndex == null ? configLabel(metaMap, absolutePath, lang) : `${copy.itemLabel} ${itemIndex + 1}`;
      return (
        <>{renderNestedBlock(absolutePath, Object.keys(nodeValue).length, renderObjectBody(nodeValue, absolutePath, mode), label)}</>
      );
    }

    return mode === "edit" ? renderFieldEditor(nodeValue, absolutePath) : renderFieldView(nodeValue, absolutePath);
  }

  return (
    <VSurface as="section" id={`config-${section.id}`} tabIndex={-1} className={sectionClassName} padding="none">
      <div className={styles.sectionHeader}>
        <div className={styles.sectionHeaderMain}>
          <h2 className={styles.sectionTitle} title={section.path}>{presentation?.sectionTitle ?? section.title}</h2>
          <p className={styles.sectionText}>{presentation?.sectionSummary ?? section.summary}</p>
        </div>
        <div className={styles.sectionHeaderActions}>
          <div className={styles.sectionToolbarGroup}>
            <VButton
              type="button"
              className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
              aria-expanded={sectionExpanded}
              onClick={() => onUiStateChange(section.id, { ...uiState, expanded: !sectionExpanded })}

                icon={<ChevronRight size={14} className={sectionExpanded ? styles.treeToggleIconExpanded : styles.treeToggleIcon}/>}
              >
                {sectionExpanded ? copy.collapseSection : copy.expandSection}
              </VButton>
          {editing ? (
            <>
              <VButton
                type="button"
                variant="primary"
                className={`${styles.primaryButton} ${styles.compactButton} ${styles.toolbarButton}`}
                isDisabled={disabled || sectionSaveBlocked}
                title={sectionSaveBlocked ? copy.saveBlockedInvalid : undefined}
                onClick={handleSave}
 icon={<Save size={14} />}>
                  {copy.saveSection}
                </VButton>
              <VButton
                type="button"
                className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
                isDisabled={disabled}
                onClick={() => {
                  onUiStateChange(section.id, {
                    ...uiState,
                    expanded: true,
                    editing: false,
                    draftValue: undefined,
                  });
                }}
 icon={<RotateCcw size={14} />}>
                  {copy.cancelSection}
                </VButton>
            </>
          ) : (
            <VButton
              type="button"
              className={`${styles.actionButton} ${styles.compactButton} ${styles.toolbarButton}`}
              isDisabled={disabled}
              onClick={() => {
                onUiStateChange(section.id, {
                  ...uiState,
                  expanded: true,
                  editing: true,
                  draftValue: clonePublicConfig(value),
                });
              }}
 icon={<Pencil size={14} />}>
                {copy.editSection}
              </VButton>
          )}
          </div>
        </div>
      </div>
      {saveError ? (
        <div className={styles.sectionSaveError} data-section-save-error="true" role="alert">
          <VErrorSummary
            tone="error"
            summary={saveError}
            label={copy.sectionErrorPrefix}
            details={copy.sectionErrorInline}
          />
        </div>
      ) : null}
      {sectionExpanded ? renderNode(editing ? draftValue : value, section.path, editing ? "edit" : "view") : null}
    </VSurface>
  );
}

/** Copy labels for avatar crop failures (subset of ConfigCopy). */
type AvatarCropErrorLabels = {
  avatarReadError: string;
  avatarCropReadError: string;
  avatarCropUnsupported: string;
  avatarCropFailed: string;
};

function loadImageForCrop(file: File, labels: AvatarCropErrorLabels): Promise<{ objectUrl: string; width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      resolve({ objectUrl, width: image.naturalWidth, height: image.naturalHeight });
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error(labels.avatarReadError));
    };
    image.src = objectUrl;
  });
}

function loadImageElement(src: string, labels: AvatarCropErrorLabels): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(labels.avatarCropReadError));
    image.src = src;
  });
}

async function createCroppedAvatarFile(draft: AvatarCropDraft, labels: AvatarCropErrorLabels): Promise<File> {
  const image = await loadImageElement(draft.objectUrl, labels);
  const canvas = document.createElement("canvas");
  canvas.width = AVATAR_CROP_OUTPUT_SIZE;
  canvas.height = AVATAR_CROP_OUTPUT_SIZE;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error(labels.avatarCropUnsupported);
  }
  const source = avatarCropSourceRect({
    imageWidth: draft.imageWidth,
    imageHeight: draft.imageHeight,
    frameSize: AVATAR_CROP_FRAME_SIZE,
    zoom: draft.zoom,
    offsetX: draft.offsetX,
    offsetY: draft.offsetY,
  });
  context.drawImage(
    image,
    source.sx,
    source.sy,
    source.size,
    source.size,
    0,
    0,
    AVATAR_CROP_OUTPUT_SIZE,
    AVATAR_CROP_OUTPUT_SIZE,
  );
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) {
        resolve(result);
        return;
      }
      reject(new Error(labels.avatarCropFailed));
    }, "image/png");
  });
  const stem = draft.fileName.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "avatar";
  return new File([blob], `${stem}-cropped.png`, { type: "image/png" });
}
