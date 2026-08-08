/**
 * Shared typography class recipes for workbench UI.
 *
 * Inspired by Material Type roles, Apple HIG text styles, and Radix/shadcn
 * size ladders — adapted for a dense desktop workbench (no fluid hero type).
 *
 * Always use the explicit font-size recipe / role tokens; never use a text
 * color utility for font tokens (Tailwind color trap — see typographyTokenContract).
 */

/** Micro meta (timestamps, rare dense tables). */
export const vuiTypeCaption =
  "[font-size:var(--vui-type-caption-size)] font-[var(--vui-weight-medium)] leading-[var(--vui-type-caption-line)] tracking-[var(--vui-tracking-normal)] text-[var(--fg-tertiary)]";

/** Uppercase / chip labels. */
export const vuiTypeLabel =
  "[font-size:var(--vui-type-label-size)] font-[var(--vui-weight-semibold)] leading-[var(--vui-type-label-line)] tracking-[var(--vui-tracking-label)] uppercase text-[var(--fg-tertiary)]";

/** Buttons, inputs, toolbar text. */
export const vuiTypeControl =
  "[font-size:var(--vui-type-control-size)] font-[var(--vui-weight-semibold)] leading-[var(--vui-type-control-line)] tracking-[var(--vui-tracking-normal)] text-[var(--fg-secondary)]";

/** Default prose / panel body. */
export const vuiTypeBody =
  "[font-size:var(--vui-type-body-size)] font-[var(--vui-weight-regular)] leading-[var(--vui-type-body-line)] tracking-[var(--vui-tracking-normal)] text-[var(--fg-primary)]";

/** Conversation transcript & long-form chat. */
export const vuiTypeChat =
  "[font-size:var(--vui-type-chat-size)] font-[var(--vui-weight-regular)] leading-[var(--vui-type-chat-line)] tracking-[var(--vui-tracking-normal)] text-[var(--fg-primary)]";

/** Empty states, short emphasis lines. */
export const vuiTypeEmphasis =
  "[font-size:var(--vui-type-emphasis-size)] font-[var(--vui-weight-semibold)] leading-[var(--vui-type-emphasis-line)] tracking-[var(--vui-tracking-tight)] text-[var(--fg-primary)]";

/** Section / route titles. */
export const vuiTypeTitle =
  "[font-size:var(--vui-type-title-size)] font-[var(--vui-weight-bold)] leading-[var(--vui-type-title-line)] tracking-[var(--vui-tracking-tight)] text-[var(--fg-primary)]";

/** Rare page-level display (avoid in dense matrices). */
export const vuiTypeDisplay =
  "[font-size:var(--vui-type-display-size)] font-[var(--vui-weight-bold)] leading-[var(--vui-type-display-line)] tracking-[var(--vui-tracking-tight)] text-[var(--fg-primary)]";

/** Monospace for code / IDs. */
export const vuiTypeMono =
  "font-[family-name:var(--font-mono)] [font-size:var(--vui-font-sm)] font-[var(--vui-weight-regular)] leading-[var(--vui-line-normal)] tracking-[var(--vui-tracking-normal)]";

export const VUI_TYPE_ROLES = [
  "caption",
  "label",
  "control",
  "body",
  "chat",
  "emphasis",
  "title",
  "display",
  "mono",
] as const;

export type VuiTypeRole = (typeof VUI_TYPE_ROLES)[number];

export const vuiTypeByRole: Record<VuiTypeRole, string> = {
  caption: vuiTypeCaption,
  label: vuiTypeLabel,
  control: vuiTypeControl,
  body: vuiTypeBody,
  chat: vuiTypeChat,
  emphasis: vuiTypeEmphasis,
  title: vuiTypeTitle,
  display: vuiTypeDisplay,
  mono: vuiTypeMono,
};
