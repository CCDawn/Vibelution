// Explicit Tailwind style map for ConfigRoute.
// Generated from the legacy ConfigRoute stylesheet during the CSS-module retirement wave;
// edit values directly as named Tailwind/arbitrary-property utilities.
import {
  vuiElevatedPanelClass,
  vuiOpaqueRowClass,
  vuiStateSelectedRowFillClass,
} from "../design/vuiSurfaceRecipes";

const panelSurface = vuiElevatedPanelClass;
const rowSurface = vuiOpaqueRowClass;
const readablePanelSurface = panelSurface;
const readableRowSurface = rowSurface;
const mutedControl =
  "[border:1px_solid_var(--border-soft)] [background:var(--vui-control-muted)] [color:var(--fg-primary)]";
const primaryControl =
  "[border:1px_solid_color-mix(in_srgb,var(--accent-warm)_26%,transparent)] [background:color-mix(in_srgb,var(--accent-warm)_14%,var(--vui-control-muted))] [color:var(--accent-warm-2)]";
const activeControl =
  `[border-color:color-mix(in_srgb,var(--accent-cool)_36%,transparent)] ${vuiStateSelectedRowFillClass} [color:var(--accent-warm-2)]`;
const sectionHeaderSurface =
  "[border-bottom:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_96%,var(--fg-primary)_4%)] [background:var(--vui-surface-toolbar)]";

const styles = {
  actionButton:
    `vui-routes-configroute actionButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:7px] [min-height:40px] [padding:0_14px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-sm)] [font-weight:650] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] ${mutedControl} hover:[cursor:pointer] hover:[border-color:var(--border-strong)] hover:[background:var(--vui-control-muted-hover)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]`,
  actionsRow:
    "vui-routes-configroute actionsRow [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap]",
  advancedEditorPanel:
    "vui-routes-configroute advancedEditorPanel [display:grid] [gap:6px] [padding:7px] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-row)] [&_summary]:[display:grid] [&_summary]:[gap:3px] [&_summary]:[cursor:pointer] [&_summary]:[color:var(--fg-primary)] [&_summary]:[font-weight:700] [&_summary_small]:[color:var(--fg-tertiary)] [&_summary_small]:[font-size:var(--vui-font-xs)] [&_summary_small]:[font-weight:500] [&_summary_small]:[line-height:1.35] [&[open]_summary]:[padding-bottom:6px]",
  agentRunItem:
    "vui-routes-configroute agentRunItem [display:grid] [grid-template-columns:minmax(150px,0.3fr)_minmax(0,1fr)_minmax(90px,auto)] [align-items:start] [gap:10px] [padding:9px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [&_div]:[display:grid] [&_div]:[gap:3px] [&_div]:[min-width:0] [&_strong]:[min-width:0] [&_strong]:[overflow-wrap:anywhere] [&_p]:[min-width:0] [&_p]:[overflow-wrap:anywhere] [&_small]:[min-width:0] [&_small]:[overflow-wrap:anywhere] [&_span]:[min-width:0] [&_span]:[overflow-wrap:anywhere] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] max-[760px]:[grid-template-columns:1fr]",
  agentRunList:
    "vui-routes-configroute agentRunList [display:grid] [gap:8px]",
  agentRunPanel:
    `vui-routes-configroute agentRunPanel [display:grid] [gap:10px] [padding:10px] ${rowSurface}`,
  agentRunPanelHeader:
    "vui-routes-configroute agentRunPanelHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:10px] [&>_div]:[display:grid] [&>_div]:[gap:3px] [&>_div]:[min-width:0] [&_strong]:[color:var(--fg-primary)] [&_strong]:[overflow-wrap:anywhere] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)]",
  applyBar:
    `vui-routes-configroute applyBar ${panelSurface} [display:flex] [align-items:center] [justify-content:space-between] [gap:14px] [padding:10px_12px] [flex-wrap:wrap] max-[720px]:[align-items:stretch]`,
  applyCopy:
    "vui-routes-configroute applyCopy [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.38] [display:grid] [gap:6px]",
  avatarCropFrame:
    "vui-routes-configroute avatarCropFrame [position:relative] [overflow:hidden] [border:1px_solid_color-mix(in_srgb,var(--accent-cool)_34%,transparent)] [background:var(--vui-gradient-route-soft),var(--vui-gradient-route-soft),var(--vui-gradient-route-soft),var(--vui-gradient-route-soft),var(--vui-surface-row)] [background-size:18px_18px] [background-position:0_0,0_9px,9px_-9px,-9px_0] [width:min(100%,320px)] [aspect-ratio:1] [border-radius:8px] [cursor:grab] [touch-action:none] [&:active]:[cursor:grabbing]",
  avatarCropHeader:
    "vui-routes-configroute avatarCropHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:12px] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [&_strong]:[display:block] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:0.95rem] [&_p]:[margin:3px_0_0] [&_p]:[color:var(--fg-tertiary)] [&_p]:[line-height:1.35] [&>_span]:[flex:0_0_auto] [&>_span]:[color:var(--fg-tertiary)] [&>_span]:[font-size:var(--vui-font-xs)]",
  avatarCropImage:
    "vui-routes-configroute avatarCropImage [position:absolute] [left:50%] [top:50%] [max-width:none] [user-select:none] [pointer-events:none] [transform-origin:center]",
  avatarCropMask:
    "vui-routes-configroute avatarCropMask [position:absolute] [inset:0] [border:1px_solid_color-mix(in_srgb,var(--fg-primary)_54%,transparent)] [box-shadow:var(--vui-shadow-inset-accent)] [pointer-events:none]",
  avatarCropPanel:
    "vui-routes-configroute avatarCropPanel [display:grid] [gap:10px] [min-width:0] [padding:10px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] !bg-[var(--vui-surface-row)]",
  avatarCropPreview:
    "vui-routes-configroute avatarCropPreview [position:relative] [overflow:hidden] [border:1px_solid_color-mix(in_srgb,var(--accent-cool)_34%,transparent)] [background:var(--vui-gradient-route-soft),var(--vui-gradient-route-soft),var(--vui-gradient-route-soft),var(--vui-gradient-route-soft),var(--vui-surface-row)] [background-size:18px_18px] [background-position:0_0,0_9px,9px_-9px,-9px_0] [width:112px] [height:112px] [border-radius:999px]",
  avatarCropPreviewWrap:
    "vui-routes-configroute avatarCropPreviewWrap [display:grid] [justify-items:center] [gap:6px]",
  avatarCropWorkspace:
    "vui-routes-configroute avatarCropWorkspace [display:grid] [grid-template-columns:minmax(0,320px)_minmax(92px,120px)] [align-items:center] [gap:14px] [min-width:0] max-[720px]:[grid-template-columns:1fr] max-[720px]:[justify-items:start]",
  avatarCropZoomField:
    "vui-routes-configroute avatarCropZoomField [display:grid] [grid-template-columns:56px_minmax(0,1fr)] [align-items:center] [gap:10px] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [&_input]:[width:100%]",
  avatarImageActions:
    "vui-routes-configroute avatarImageActions [display:flex] [align-items:center] [gap:8px] [flex-wrap:wrap]",
  avatarImageCard:
    "vui-routes-configroute avatarImageCard [grid-template-columns:minmax(132px,0.38fr)_minmax(0,1fr)]",
  avatarImageDropButton:
    "vui-routes-configroute avatarImageDropButton [position:relative] [display:grid] [flex:0_0_auto] [place-items:center] [width:56px] [height:56px] [border-radius:999px] [cursor:pointer] [&:hover_.avatarImagePreview]:[border-color:color-mix(in_srgb,var(--accent-warm)_44%,var(--border-hairline))] [&:hover_.avatarImagePreview]:[box-shadow:var(--vui-shadow-accent)] [&:hover_.avatarImagePlaceholder]:[border-color:color-mix(in_srgb,var(--accent-warm)_44%,var(--border-hairline))] [&:hover_.avatarImagePlaceholder]:[box-shadow:var(--vui-shadow-accent)] [&_input]:[position:absolute] [&_input]:[inset:0] [&_input]:[opacity:0] [&_input]:[pointer-events:none]",
  avatarImageEditor:
    "vui-routes-configroute avatarImageEditor [display:grid] [gap:10px] [min-width:0]",
  avatarImageMeta:
    "vui-routes-configroute avatarImageMeta [display:grid] [gap:3px] [min-width:0] [&_strong]:[overflow:hidden] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[line-height:1.2] [&_strong]:[text-overflow:ellipsis] [&_strong]:[white-space:nowrap] [&_span]:[overflow:hidden] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-family:var(--font-mono)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.25] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  avatarImagePlaceholder:
    "vui-routes-configroute avatarImagePlaceholder [width:56px] [height:56px] [flex:0_0_auto] [border-radius:999px] [border:1px_solid_var(--border-hairline)] [background:var(--vui-surface-row)] [display:grid] [place-items:center] [color:var(--fg-tertiary)]",
  avatarImagePreview:
    "vui-routes-configroute avatarImagePreview [width:56px] [height:56px] [flex:0_0_auto] [border-radius:999px] [border:1px_solid_var(--border-hairline)] [background:var(--vui-surface-row)] [object-fit:cover]",
  avatarImageUploadCue:
    "vui-routes-configroute avatarImageUploadCue [position:absolute] [right:-1px] [bottom:-1px] [display:grid] [place-items:center] [width:20px] [height:20px] [border:1px_solid_var(--border-hairline)] [border-radius:999px] !bg-[var(--vui-surface-panel)] [color:var(--fg-primary)] [box-shadow:var(--vui-shadow-soft)]",
  avatarImageValue:
    "vui-routes-configroute avatarImageValue [display:flex] [align-items:center] [gap:8px] [min-width:0] [max-width:100%] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [overflow-wrap:anywhere]",
  buttonBlock:
    "vui-routes-configroute buttonBlock [width:auto] [max-width:100%]",
  cardBadges:
    "vui-routes-configroute cardBadges [display:flex] [align-items:center] [gap:8px] [flex-wrap:wrap]",
  cardHeader:
    "vui-routes-configroute cardHeader [display:grid] [grid-template-columns:minmax(0,1fr)_auto] [align-items:start] [gap:10px] [&>_div:first-child]:[min-width:0]",
  cardHeaderActions:
    "vui-routes-configroute cardHeaderActions [display:flex] [align-items:center] [gap:10px] [min-width:max-content] [justify-content:end] max-[1120px]:[align-items:stretch] max-[1120px]:[flex-direction:column]",
  cardMeta:
    "vui-routes-configroute cardMeta [margin:0] [color:var(--fg-secondary)] [line-height:1.38] [&_span]:[overflow-wrap:anywhere] [&_strong]:[overflow-wrap:anywhere] [display:grid] [gap:6px] [font-size:var(--vui-font-xs)] [min-width:0]",
  cardSubtle:
    "vui-routes-configroute cardSubtle [margin:0] [color:var(--fg-secondary)] [line-height:1.38] [min-width:0] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  cardSummaryLine:
    "vui-routes-configroute cardSummaryLine [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [min-width:0] [&_span]:[min-width:0] [&_span]:[max-width:100%] [&_span]:[padding:3px_7px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:999px] [&_span]:[background:var(--vui-surface-row)] [&_span]:[overflow:hidden] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap]",
  cardTitle:
    "vui-routes-configroute cardTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:0.96rem] [font-weight:600] [min-width:0] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  checkboxField:
    "vui-routes-configroute checkboxField [&_input]:[width:auto] [&_input]:[min-height:20px] [&_input]:[justify-self:start]",
  compactButton:
    "vui-routes-configroute compactButton [min-height:27px] [padding:0_8px] [font-size:var(--vui-font-xs)]",
  configProgressiveBody:
    "vui-routes-configroute configProgressiveBody [display:grid] [gap:12px] [margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&_.treeFieldCardView]:[grid-template-columns:minmax(0,1fr)] [&_.treeFieldCardView]:[gap:5px] [&_.treeFieldCardView]:[min-height:92px] [&_.treeFieldHead]:[grid-column:1] [&_.treeFieldHead]:[grid-row:1] [&_.treeFieldValue]:[grid-column:1] [&_.treeFieldValue]:[grid-row:2] [&_.treeHint]:[grid-column:1] [&_.treeHint]:[grid-row:3] [&_.treeHint]:[-webkit-line-clamp:1] [&_.treeFieldLabel]:[overflow:visible] [&_.treeFieldLabel]:[text-overflow:clip] [&_.treeFieldLabel]:[white-space:normal] [&_.treeFieldCardEdit_.field]:[grid-template-columns:minmax(0,1fr)]",
  configCompactPathProgressiveBody:
    "vui-routes-configroute configCompactPathProgressiveBody [gap:8px] [&_.configTierHeaderCopy]:![display:flex] [&_.configTierHeaderCopy]:![align-items:baseline] [&_.configTierHeaderCopy]:![gap:8px] [&_.configTierHeaderCopy_span]:[overflow:hidden] [&_.configTierHeaderCopy_span]:[text-overflow:ellipsis] [&_.configTierHeaderCopy_span]:[white-space:nowrap] [&_.treeFieldCardView]:![grid-template-columns:minmax(150px,0.42fr)_minmax(0,1fr)] [&_.treeFieldCardView]:![grid-template-rows:auto_auto] [&_.treeFieldCardView]:![gap:4px_10px] [&_.treeFieldCardView]:![min-height:64px] [&_.treeFieldCardView]:![padding:8px] [&_.treeFieldHead]:![grid-column:1] [&_.treeFieldHead]:![grid-row:1] [&_.treeHint]:![grid-column:1] [&_.treeHint]:![grid-row:2] [&_.treeHint]:![-webkit-line-clamp:1] [&_.treeFieldValue]:![grid-column:2] [&_.treeFieldValue]:![grid-row:1/span_2] [&_.treeFieldValue]:![align-self:center] [&_.treeObjectBlock_>_.treeToggle]:![width:100%] [&_.treeObjectBlock_>_.treeToggle]:![min-height:50px] [&_.treeObjectBlock_>_.treeToggle]:![justify-self:stretch]",
  configCompactAdvancedProgressiveBody:
    "vui-routes-configroute configCompactAdvancedProgressiveBody [&_.configAdvancedToggle]:![min-height:64px] [&_.configAdvancedToggle_.configTierHeaderCopy]:![display:grid] [&_.configAdvancedToggle_.configTierHeaderCopy]:![align-items:initial] [&_.configAdvancedToggle_.configTierHeaderCopy]:![gap:3px] [&_.configAdvancedToggle_.configTierHeaderCopy_span]:![white-space:normal]",
  configCommonGridOne:
    "vui-routes-configroute configCommonGridOne ![grid-template-columns:minmax(0,1fr)]",
  configCommonGridFour:
    "vui-routes-configroute configCommonGridFour ![grid-template-columns:repeat(4,minmax(0,1fr))] max-[1180px]:![grid-template-columns:repeat(2,minmax(0,1fr))]",
  configCommonGridContext:
    "vui-routes-configroute configCommonGridContext ![grid-template-columns:repeat(3,minmax(0,1fr))] max-[1180px]:![grid-template-columns:repeat(2,minmax(0,1fr))]",
  configCommonGridTwo:
    "vui-routes-configroute configCommonGridTwo ![grid-template-columns:repeat(2,minmax(0,1fr))]",
  configCommonGridThree:
    "vui-routes-configroute configCommonGridThree ![grid-template-columns:repeat(3,minmax(0,1fr))] max-[1180px]:![grid-template-columns:repeat(2,minmax(0,1fr))]",
  configAdvancedGrid:
    "vui-routes-configroute configAdvancedGrid ![grid-template-columns:repeat(3,minmax(0,1fr))] max-[1180px]:![grid-template-columns:repeat(2,minmax(0,1fr))]",
  configTier:
    "vui-routes-configroute configTier [display:grid] [gap:7px] [min-width:0]",
  configTierHeader:
    "vui-routes-configroute configTierHeader [display:flex] [align-items:center] [justify-content:space-between] [gap:12px] [min-width:0] [padding:2px_2px_0]",
  configTierHeaderCopy:
    "vui-routes-configroute configTierHeaderCopy [display:grid] [gap:3px] [min-width:0] [text-align:left] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_strong]:[font-weight:700] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.35] [&_span]:[overflow-wrap:anywhere]",
  configAdvancedTier:
    "vui-routes-configroute configAdvancedTier [padding-top:10px] [border-top:1px_solid_var(--border-hairline)]",
  configAdvancedToggle:
    "vui-routes-configroute configAdvancedToggle w-full [display:flex] [align-items:center] [justify-content:space-between] [gap:14px] [min-height:58px] [padding:10px_12px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_94%,transparent)] [border-radius:8px] [background:var(--vui-surface-row)] [color:inherit] [text-align:left] hover:[border-color:color-mix(in_srgb,var(--accent-cool)_34%,var(--border-strong))] hover:[background:var(--vui-surface-row-hover)] focus-visible:[outline:2px_solid_var(--accent-cool)] focus-visible:[outline-offset:2px]",
  configAdvancedToggleMeta:
    "vui-routes-configroute configAdvancedToggleMeta [display:flex] [align-items:center] [justify-content:end] [gap:8px] [flex:0_0_auto]",
  configAdvancedBody:
    "vui-routes-configroute configAdvancedBody [display:grid] [gap:7px] [padding-top:2px]",
  configDenseSection:
    "vui-routes-configroute configDenseSection [&>_.treeGrid]:[grid-template-columns:repeat(3,minmax(220px,1fr))] [&>_.treeGrid]:[gap:7px] [&_.treeFieldCardView]:[grid-template-columns:minmax(108px,0.34fr)_minmax(0,1fr)] [&_.treeFieldCardView]:[gap:4px_7px] [&_.treeFieldCardView]:[min-height:34px] [&_.treeFieldCardView]:[padding:6px] [&_.treeFieldCardEdit]:[gap:5px] [&_.treeFieldCardEdit]:[padding:7px] [&_.treeObjectCell_.treeObjectBlock]:[min-height:38px] [&_.treeObjectCell_.treeObjectBlock]:[padding:7px] [&_.treeObjectCell_.treeNestedBlock]:[min-height:38px] [&_.treeObjectCell_.treeNestedBlock]:[padding:7px] [&_.treeObjectCell_.treeToggle]:[min-height:30px] max-[1500px]:[&>_.treeGrid]:[grid-template-columns:repeat(2,minmax(220px,1fr))] max-[860px]:[&>_.treeGrid]:[grid-template-columns:1fr]",
  configDiscoverySection:
    "vui-routes-configroute configDiscoverySection [align-self:end] [min-height:0] [&>_.treeGrid]:[align-content:start] [&>_.treeGrid]:[grid-template-columns:repeat(3,minmax(220px,1fr))] [&>_.treeGrid]:[gap:7px] [&_.treeFieldCardView]:[grid-template-columns:minmax(116px,0.36fr)_minmax(0,1fr)] [&_.treeFieldCardView]:[min-height:40px] [&_.treeFieldCardView]:[padding:6px_7px] [&_.treeFieldLabel]:[overflow:hidden] [&_.treeFieldLabel]:[text-overflow:ellipsis] [&_.treeFieldLabel]:[white-space:nowrap] [&_.treeFieldValue]:[overflow:hidden] [&_.treeFieldValue]:[text-overflow:ellipsis] [&_.treeFieldValue]:[white-space:nowrap] max-[1380px]:[&>_.treeGrid]:[grid-template-columns:repeat(2,minmax(220px,1fr))] max-[860px]:[&>_.treeGrid]:[grid-template-columns:1fr] max-[720px]:[min-height:0]",
  configEditorSection:
    "vui-routes-configroute configEditorSection [&>_.treeGrid]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.treeStack]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.helperText]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)]",
  configStatusActions:
    "vui-routes-configroute configStatusActions [display:flex] [align-items:center] [justify-content:end] [gap:6px] [flex-wrap:wrap] max-[720px]:[justify-content:start]",
  configHeader:
    `vui-routes-configroute configHeader ${readablePanelSurface} [display:grid] [grid-template-columns:minmax(0,1fr)] [align-items:stretch] [gap:8px] [padding:10px_12px] [min-width:0] [border-radius:0]`,
  configStatusBand:
    `vui-routes-configroute configStatusBand ${readablePanelSurface} [display:grid] [grid-template-columns:1fr] [align-items:stretch] [gap:8px] [padding:8px_10px] [min-width:0]`,
  configStatusCopy:
    "vui-routes-configroute configStatusCopy [display:grid] [gap:5px] [min-width:0]",
  configStatusMeta:
    "vui-routes-configroute configStatusMeta [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap] [min-width:0]",
  configStatusPath:
    "vui-routes-configroute configStatusPath [display:inline-flex] [align-items:center] [min-height:24px] [max-width:100%] [padding:0_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [background:var(--vui-surface-workspace)] [color:var(--fg-secondary)] [font-family:var(--font-mono)] [font-size:var(--vui-font-xs)] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  content:
    "vui-routes-configroute content [display:grid] [grid-template-rows:auto_auto_minmax(0,1fr)] [align-content:stretch] [min-width:0] [min-height:0] [height:100%] [overflow:hidden]",
  pageViewport:
    "vui-routes-configroute pageViewport [display:grid] [align-content:start] [gap:12px] min-w-0 min-h-0 overflow-y-auto overflow-x-hidden [padding:12px] [scrollbar-gutter:stable] [&:has(>_.providerModelsLayout)]:[align-content:stretch] [&:has(>_.providerModelsLayout)]:[grid-template-rows:minmax(0,1fr)]",
  contentModels:
    "vui-routes-configroute contentModels [align-content:stretch] [grid-template-rows:minmax(0,1fr)_auto] [height:100%] [max-height:calc(100dvh_-_76px)] [min-width:0] [&:has(>_.notice)]:[grid-template-rows:auto_minmax(0,1fr)_auto] [&>_.configDiscoverySection:last-child]:[display:grid] [&>_.configDiscoverySection:last-child]:[grid-template-rows:auto_auto] max-[720px]:[max-height:none] max-[720px]:[height:auto] max-[720px]:[overflow:visible]",
  providerModelsLayout:
    "vui-routes-configroute providerModelsLayout grid h-full min-h-0 min-w-0 [grid-template-rows:auto_minmax(0,1fr)] gap-3 overflow-hidden",
  providerModeButton:
    "vui-routes-configroute providerModeButton min-h-10 px-3.5 [font-size:var(--vui-font-sm)] font-semibold",
  providerRouteEditSurface:
    "vui-routes-configroute providerRouteEditSurface grid min-w-0 gap-2",
  providerRouteEditGrid:
    "vui-routes-configroute providerRouteEditGrid grid min-w-0 grid-cols-3 gap-2 max-[720px]:grid-cols-1",
  providerRouteEditField:
    "vui-routes-configroute providerRouteEditField grid min-w-0 gap-1",
  providerRouteEditWarning:
    "vui-routes-configroute providerRouteEditWarning m-0 [font-size:var(--vui-font-xs)] text-[var(--state-warning)]",
  countPill:
    "vui-routes-configroute countPill [display:inline-flex] [align-items:center] [justify-content:center] [min-width:30px] [min-height:28px] [padding:0_9px] [border:1px_solid_var(--border-hairline)] [border-radius:999px] [color:var(--fg-secondary)] [background:var(--vui-surface-row)] [font-size:var(--vui-font-xs)] [font-weight:700]",
  dangerButton:
    `vui-routes-configroute dangerButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:7px] [min-height:40px] [padding:0_14px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-sm)] [font-weight:650] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] ${mutedControl} [color:var(--state-error)] [border-color:color-mix(in_srgb,var(--state-error)_24%,transparent)] [background:color-mix(in_srgb,var(--state-error)_12%,var(--vui-control-muted))] hover:[cursor:pointer] hover:[border-color:color-mix(in_srgb,var(--state-error)_36%,transparent)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]`,
  detailCard:
    `vui-routes-configroute detailCard ${rowSurface} [display:grid] [gap:6px] [padding:8px] [align-content:center] [min-height:48px] [&>_span]:[color:var(--fg-tertiary)] [&>_span]:[font-size:var(--vui-font-xs)] [&>_span]:[font-weight:600] [&>_strong]:[color:var(--fg-primary)] [&>_strong]:[font-size:0.98rem] [&>_strong]:[overflow-wrap:anywhere]`,
  editorWrap:
    "vui-routes-configroute editorWrap [min-height:360px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [overflow:hidden] [background:var(--vui-surface-workspace)] [&.cm-editor]:[height:100%] [&.cm-editor]:[min-height:360px] [&.cm-scroller]:[overflow:auto]",
  eyebrow:
    "vui-routes-configroute eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  field:
    "vui-routes-configroute field [display:grid] [grid-template-columns:minmax(12rem,0.34fr)_minmax(0,1fr)] [align-items:start] [gap:10px_16px] [&_span]:[overflow-wrap:anywhere] [&>_span]:[padding-top:10px] [&>_span]:[color:var(--fg-secondary)] [&>_span]:[font-size:var(--vui-font-sm)] [&>_span]:[font-weight:650] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[border:1px_solid_var(--border-soft)] [&_input]:[border-radius:var(--control-radius)] [&_input]:[background:var(--vui-surface-workspace)] [&_input]:[color:var(--fg-primary)] [&_input]:[padding:8px_12px] [&_input]:[font:inherit] [&_input]:[font-size:var(--vui-font-sm)] [&_select]:[width:100%] [&_select]:[min-width:0] [&_select]:[border:1px_solid_var(--border-soft)] [&_select]:[border-radius:var(--control-radius)] [&_select]:[background:var(--vui-surface-workspace)] [&_select]:[color:var(--fg-primary)] [&_select]:[padding:8px_12px] [&_select]:[font:inherit] [&_select]:[font-size:var(--vui-font-sm)] [&_textarea]:[width:100%] [&_textarea]:[min-width:0] [&_textarea]:[border:1px_solid_var(--border-soft)] [&_textarea]:[border-radius:var(--control-radius)] [&_textarea]:[background:var(--vui-surface-workspace)] [&_textarea]:[color:var(--fg-primary)] [&_textarea]:[padding:10px_12px] [&_textarea]:[font:inherit] [&_textarea]:[font-size:var(--vui-font-sm)] [&_input]:[min-height:var(--control-height)] [&_select]:[min-height:var(--control-height)]",
  fieldHint:
    "vui-routes-configroute fieldHint [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [line-height:1.36]",
  fileUploadButton:
    "vui-routes-configroute fileUploadButton [position:relative] [overflow:hidden] [cursor:pointer] [&_input]:[position:absolute] [&_input]:[inset:0] [&_input]:[opacity:0] [&_input]:[pointer-events:none]",
  findingCard:
    "vui-routes-configroute findingCard [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [display:grid] [gap:10px] [padding:12px]",
  findingEvidence:
    "vui-routes-configroute findingEvidence [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [gap:8px] [&_span]:[min-width:0] [&_span]:[padding:9px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:8px] [&_span]:[background:var(--vui-surface-row)] [&_span]:[display:grid] [&_span]:[gap:4px] [&_span]:[color:var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[overflow-wrap:anywhere] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:600] [&_strong]:[text-transform:uppercase] [&_strong]:[letter-spacing:0.06em] max-[720px]:[grid-template-columns:1fr]",
  findingHeader:
    "vui-routes-configroute findingHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:12px] [&_h4]:[margin:0] [&_h4]:[color:var(--fg-primary)] [&_h4]:[margin-top:4px] [&_h4]:[font-size:0.94rem]",
  findingList:
    "vui-routes-configroute findingList [display:grid] [gap:10px]",
  findingRecommendation:
    "vui-routes-configroute findingRecommendation [min-width:0] [padding:9px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:600] [&_strong]:[text-transform:uppercase] [&_strong]:[letter-spacing:0.06em] [display:grid] [gap:5px] [margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)]",
  formActions:
    "vui-routes-configroute formActions [display:flex] [align-items:center] [justify-content:flex-start] [gap:8px] [flex-wrap:wrap]",
  formGrid:
    "vui-routes-configroute formGrid [display:grid] [gap:6px] [grid-template-columns:repeat(auto-fit,minmax(190px,1fr))] max-[1120px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  formGridWide:
    "vui-routes-configroute formGridWide [display:grid] [gap:6px] [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  formGridWideSpan:
    "vui-routes-configroute formGridWideSpan [grid-column:1/-1]",
  formHeader:
    "vui-routes-configroute formHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:36px] [padding:7px_9px] [border-bottom:1px_solid_var(--border-hairline)] max-[1120px]:[align-items:stretch] max-[1120px]:[flex-direction:column]",
  formHeaderIntro:
    "vui-routes-configroute formHeaderIntro [display:flex] [align-items:center] [gap:10px] [align-items:start]",
  formSurface:
    `vui-routes-configroute formSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:hidden] [&>_:where(_.formGrid,.formGridWide,.field,.actionsRow,.formActions,.toggleGrid,.advancedEditorPanel,.fieldHint,.inlineFormError,.helperText_)]:[margin:7px_9px_0] [&>_:where(.fieldHint,.inlineFormError,.helperText):last-child]:[margin-bottom:8px] [&>_:where(.actionsRow,.formActions,.toggleGrid):last-child]:[margin-bottom:8px] [&>_.formHeader_+_:where(.formGrid,.formGridWide,.field,.helperText)]:[margin-top:7px]`,
  hashGrid:
    "vui-routes-configroute hashGrid [display:grid] [gap:8px] [grid-template-columns:minmax(280px,1.4fr)_minmax(180px,0.6fr)] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  hashValue:
    "vui-routes-configroute hashValue [overflow:auto] [overflow-wrap:anywhere] [font-family:Consolas,'SFMono-Regular',monospace] [font-size:var(--vui-font-xs)] [color:var(--fg-primary)]",
  healthBadgeBlocked:
    "vui-routes-configroute healthBadgeBlocked [color:var(--state-error)] [background:color-mix(in_srgb,var(--state-error)_14%,transparent)] [border-color:color-mix(in_srgb,var(--state-error)_26%,transparent)]",
  healthMetric:
    "vui-routes-configroute healthMetric [color:var(--fg-primary)] [font-family:var(--font-display)] [font-size:1.8rem] [line-height:1]",
  healthPanel:
    "vui-routes-configroute healthPanel [display:grid] [align-content:start] [gap:10px] [min-width:0]",
  healthPanelHeader:
    "vui-routes-configroute healthPanelHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:12px] [&_h3]:[margin:0] [&_h3]:[color:var(--fg-primary)] [&_h3]:[font-size:0.96rem]",
  healthSummaryGrid:
    "vui-routes-configroute healthSummaryGrid [display:grid] [gap:8px] [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  healthWorkbenchGrid:
    "vui-routes-configroute healthWorkbenchGrid [display:grid] [grid-template-columns:minmax(0,1.35fr)_minmax(280px,0.65fr)] [gap:12px] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  helperText:
    "vui-routes-configroute helperText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  inlineBadge:
    "vui-routes-configroute inlineBadge [display:inline-flex] [align-items:center] [justify-content:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [border:1px_solid_transparent] [font-size:var(--vui-font-xs)] [white-space:nowrap] [color:var(--fg-secondary)] [background:var(--vui-surface-row)]",
  inlineBadgeMuted:
    "vui-routes-configroute inlineBadgeMuted [color:var(--fg-tertiary)] [background:var(--vui-surface-row)] [border-color:var(--border-hairline)]",
  inlineBadgeSuccess:
    "vui-routes-configroute inlineBadgeSuccess [color:var(--state-success)] [background:color-mix(in_srgb,var(--state-success)_12%,transparent)] [border-color:color-mix(in_srgb,var(--state-success)_22%,transparent)]",
  inlineBadgeWarning:
    "vui-routes-configroute inlineBadgeWarning [color:var(--accent-warm-2)] [background:color-mix(in_srgb,var(--accent-warm)_12%,transparent)] [border-color:color-mix(in_srgb,var(--accent-warm)_22%,transparent)]",
  inlineError:
    "vui-routes-configroute inlineError [margin:0] [color:var(--state-error)] [font-size:var(--vui-font-xs)] [line-height:1.35]",
  inlineFormError:
    "vui-routes-configroute inlineFormError [margin:0] [padding:8px_10px] [border:1px_solid_color-mix(in_srgb,var(--state-error)_28%,transparent)] [border-radius:var(--control-radius)] [background:color-mix(in_srgb,var(--state-error)_12%,transparent)] [color:var(--state-error)] [line-height:1.42] [overflow-wrap:anywhere]",
  keyLocationLine:
    "vui-routes-configroute keyLocationLine [display:grid] [gap:2px] [&_strong]:[color:var(--fg-tertiary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:600] [&_span]:[overflow-wrap:anywhere]",
  leaveGuardActions:
    "vui-routes-configroute leaveGuardActions [display:flex] [justify-content:end] [gap:8px] [flex-wrap:wrap]",
  leaveGuardCopy:
    "vui-routes-configroute leaveGuardCopy [display:grid] [gap:7px] [&_h2]:[margin:0] [&_p]:[margin:0] [&_h2]:[color:var(--fg-primary)] [&_h2]:[font-size:1.06rem] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.42]",
  leaveGuardOverlay:
    "vui-routes-configroute leaveGuardOverlay [position:fixed] [inset:0] [z-index:80] [display:grid] [place-items:center] [padding:18px] [background:color-mix(in_srgb,var(--bg-canvas)_68%,transparent)] [backdrop-filter:blur(6px)]",
  leaveGuardPanel:
    `vui-routes-configroute leaveGuardPanel [display:grid] [gap:14px] [width:min(520px,100%)] [padding:16px] ${panelSurface} [border-radius:8px] [box-shadow:var(--shadow-strong)]`,
  loadingBoard:
    `vui-routes-configroute loadingBoard ${panelSurface} [display:grid] [grid-template-rows:auto_auto_minmax(0,1fr)] [align-content:start] [gap:8px] [padding:10px] [min-width:0] [overflow:hidden]`,
  loadingBoardHeader:
    "vui-routes-configroute loadingBoardHeader [display:grid] [grid-template-columns:minmax(180px,0.9fr)_minmax(100px,0.32fr)_minmax(100px,0.32fr)] [gap:7px] [&_span]:[display:block] [&_span]:[border-radius:6px] [&_span]:[background:var(--vui-gradient-route-soft)] [&_span]:[min-height:32px]",
  loadingMetricGrid:
    "vui-routes-configroute loadingMetricGrid [&_strong]:[display:block] [&_strong]:[border-radius:6px] [&_strong]:[background:var(--vui-gradient-route-soft)] [display:grid] [grid-template-columns:repeat(4,minmax(0,1fr))] [gap:7px] [&_span]:[display:grid] [&_span]:[gap:5px] [&_span]:[min-height:54px] [&_span]:[padding:8px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:8px] [&_span]:[background:var(--vui-surface-row)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[text-transform:uppercase] [&_strong]:[min-height:16px]",
  loadingNavActive:
    "vui-routes-configroute loadingNavActive",
  loadingNavList:
    "vui-routes-configroute loadingNavList [display:grid] [gap:5px] [margin-top:4px] [&_span]:[display:flex] [&_span]:[align-items:center] [&_span]:[min-height:27px] [&_span]:[padding:0_8px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:var(--control-radius)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[background:var(--vui-surface-row)] [&_.loadingNavActive]:[border-color:color-mix(in_srgb,var(--accent-cool)_32%,transparent)] [&_.loadingNavActive]:[background:color-mix(in_srgb,var(--accent-cool)_10%,transparent)] [&_.loadingNavActive]:[color:var(--accent-warm-2)]",
  loadingNavPanel:
    `vui-routes-configroute loadingNavPanel ${panelSurface} [display:grid] [align-content:start] [gap:8px] [padding:10px] [min-height:0]`,
  loadingShell:
    "vui-routes-configroute loadingShell [grid-column:1/-1] [display:grid] [grid-template-columns:minmax(240px,var(--sidebar-width,306px))_minmax(0,1fr)] [gap:6px] [min-height:0] [height:100%] max-[1120px]:[grid-template-columns:1fr]",
  loadingShellError:
    "vui-routes-configroute loadingShellError [&_.loadingNavPanel]:[border-color:color-mix(in_srgb,var(--state-error)_28%,transparent)] [&_.loadingBoard]:[border-color:color-mix(in_srgb,var(--state-error)_28%,transparent)]",
  loadingSpecGrid:
    "vui-routes-configroute loadingSpecGrid [&_span]:[display:block] [&_span]:[border-radius:6px] [&_span]:[background:var(--vui-gradient-route-soft)] [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [gap:7px] [&_span]:[min-height:76px]",
  loadingSurface:
    `vui-routes-configroute loadingSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:hidden] [place-items:start]`,
  logHelperCard:
    "vui-routes-configroute logHelperCard [display:grid] [gap:6px] [padding:8px] [align-content:start] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)]",
  logHelperGrid:
    "vui-routes-configroute logHelperGrid [display:grid] [gap:8px] [grid-template-columns:repeat(auto-fit,minmax(280px,1fr))] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  logHelperHeader:
    "vui-routes-configroute logHelperHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:12px] max-[1120px]:[align-items:stretch] max-[1120px]:[flex-direction:column]",
  logHelperMetaGrid:
    "vui-routes-configroute logHelperMetaGrid [display:grid] [grid-template-columns:repeat(4,minmax(0,1fr))] [gap:8px] [&_span]:[min-width:0] [&_span]:[padding:10px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:8px] [&_span]:[background:var(--vui-surface-row)] [&_span]:[display:grid] [&_span]:[gap:4px] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:0.9rem] [&_strong]:[overflow-wrap:anywhere] max-[720px]:[grid-template-columns:1fr]",
  logHelperSignal:
    "vui-routes-configroute logHelperSignal [min-width:0] [padding:10px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [display:grid] [gap:6px] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[overflow-wrap:anywhere]",
  matrixGrid:
    "vui-routes-configroute matrixGrid [display:grid] [gap:8px] [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  metricCard:
    `vui-routes-configroute metricCard ${rowSurface} [display:grid] [gap:2px] [padding:7px_8px] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:[color:var(--fg-secondary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.2]`,
  modelCard:
    "vui-routes-configroute modelCard [display:grid] [gap:6px] [padding:8px]",
  modelCenterSummaryBar:
    "vui-routes-configroute modelCenterSummaryBar [display:flex] [align-items:center] [gap:5px] [flex-wrap:wrap] [margin:6px_var(--config-section-x)_0] [&_span]:[display:inline-flex] [&_span]:[align-items:center] [&_span]:[gap:4px] [&_span]:[min-height:25px] [&_span]:[padding:0_8px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:999px] [&_span]:[background:var(--vui-surface-row)] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_.summaryBarWarning]:[border-color:color-mix(in_srgb,var(--state-warning)_34%,var(--border-hairline))] [&_.summaryBarWarning]:[color:var(--state-warning)] [&_.summaryBarWarning_strong]:[color:var(--state-warning)]",
  modelInventoryTable:
    "vui-routes-configroute modelInventoryTable [min-width:1080px] [&_th:first-child]:[min-width:240px] [&_td:first-child]:[min-width:240px] [&_th:nth-child(2)]:[min-width:210px] [&_td:nth-child(2)]:[min-width:210px] [&_th:nth-child(3)]:[min-width:260px] [&_td:nth-child(3)]:[min-width:260px] [&_th:nth-child(5)]:[min-width:210px] [&_td:nth-child(5)]:[min-width:210px] [&_th:nth-child(6)]:[min-width:150px] [&_td:nth-child(6)]:[min-width:150px] [&_.profileTaskCell_strong]:[display:block] [&_.profileTaskCell_strong]:[max-width:100%] [&_.profileTaskCell_strong]:[overflow:hidden] [&_.profileTaskCell_strong]:[overflow-wrap:normal] [&_.profileTaskCell_strong]:[text-overflow:ellipsis] [&_.profileTaskCell_strong]:[white-space:nowrap] [&_.profileModelCell_strong]:[display:block] [&_.profileModelCell_strong]:[max-width:100%] [&_.profileModelCell_strong]:[overflow:hidden] [&_.profileModelCell_strong]:[overflow-wrap:normal] [&_.profileModelCell_strong]:[text-overflow:ellipsis] [&_.profileModelCell_strong]:[white-space:nowrap] [&_.profileMetaCell_strong]:[display:block] [&_.profileMetaCell_strong]:[max-width:100%] [&_.profileMetaCell_strong]:[overflow:hidden] [&_.profileMetaCell_strong]:[overflow-wrap:normal] [&_.profileMetaCell_strong]:[text-overflow:ellipsis] [&_.profileMetaCell_strong]:[white-space:nowrap] [&_.profileTaskCell_span]:[display:block] [&_.profileTaskCell_span]:[max-width:100%] [&_.profileTaskCell_span]:[overflow:hidden] [&_.profileTaskCell_span]:[overflow-wrap:normal] [&_.profileTaskCell_span]:[text-overflow:ellipsis] [&_.profileTaskCell_span]:[white-space:nowrap] [&_.profileModelCell_span]:[display:block] [&_.profileModelCell_span]:[max-width:100%] [&_.profileModelCell_span]:[overflow:hidden] [&_.profileModelCell_span]:[overflow-wrap:normal] [&_.profileModelCell_span]:[text-overflow:ellipsis] [&_.profileModelCell_span]:[white-space:nowrap] [&_.profileMetaCell_span:not(.inlineBadge)]:[display:block] [&_.profileMetaCell_span:not(.inlineBadge)]:[max-width:100%] [&_.profileMetaCell_span:not(.inlineBadge)]:[overflow:hidden] [&_.profileMetaCell_span:not(.inlineBadge)]:[overflow-wrap:normal] [&_.profileMetaCell_span:not(.inlineBadge)]:[text-overflow:ellipsis] [&_.profileMetaCell_span:not(.inlineBadge)]:[white-space:nowrap] [&_.profileTaskCell_strong]:[font-size:var(--vui-font-xs)] [&_.profileTaskCell_strong]:[line-height:1.12] [&_.profileModelCell_strong]:[font-size:var(--vui-font-xs)] [&_.profileModelCell_strong]:[line-height:1.12] [&_.profileMetaCell_strong]:[font-size:var(--vui-font-xs)] [&_.profileMetaCell_strong]:[line-height:1.12] [&_.profileTaskCell_span]:[margin-bottom:2px] [&_.profileTaskCell_span]:[font-size:var(--vui-font-xs)] [&_.profileTaskCell_span]:[line-height:1.14] [&_.profileModelCell_span]:[margin-bottom:2px] [&_.profileModelCell_span]:[font-size:var(--vui-font-xs)] [&_.profileModelCell_span]:[line-height:1.14] [&_.profileMetaCell_span:not(.inlineBadge)]:[margin-bottom:2px] [&_.profileMetaCell_span:not(.inlineBadge)]:[font-size:var(--vui-font-xs)] [&_.profileMetaCell_span:not(.inlineBadge)]:[line-height:1.14] [&_.profileTableActions]:[display:grid] [&_.profileTableActions]:[gap:4px] [&_.profileTableActions]:[align-items:stretch] [&_.profileTableActions_.compactButton]:[justify-content:start] [&_.profileTableActions_.compactButton]:[min-height:24px] [&_.profileTableActions_.compactButton]:[padding-inline:6px] [&_.profileTableActions_.compactButton]:[font-size:var(--vui-font-xs)] [&_.inlineBadge]:[min-height:19px] [&_.inlineBadge]:[padding-inline:6px] [&_.inlineBadge]:[font-size:var(--vui-font-xs)]",
  modelLibrarySection:
    "vui-routes-configroute modelLibrarySection [--config-section-y:6px] [grid-template-rows:auto_auto_auto_auto_auto_minmax(0,1fr)] [min-height:0] [overflow:auto] [&_.sectionHeader]:[min-height:34px] [&_.sectionHeader]:[padding-block:6px] [&>_.sectionText]:[max-width:none] [&>_.sectionText]:[padding-top:5px] [&>_.sectionText]:[overflow:hidden] [&>_.sectionText]:[text-overflow:ellipsis] [&>_.sectionText]:[white-space:nowrap] [&_.modelCenterSummaryBar]:[margin-top:5px] [&_.modelLibraryTestBar]:[gap:6px] [&_.modelLibraryTestBar]:[padding:6px_8px] [&_.modelLibraryTestBar]:[border-radius:7px] [&_.modelLibraryTestSelect]:[min-width:min(320px,100%)] [&_.modelLibraryTestSelect]:[flex-basis:260px] [&_.formHeader]:[min-height:32px] [&_.formHeader]:[padding:5px_8px] [&_.profileTableWrap]:[height:100%] [&_.profileTableWrap]:[max-height:none] [&_.profileTableWrap]:[min-height:0] [&_.profileTableWrap]:[overflow:auto] [&_.profileTable_th]:[padding:5px_7px] [&_.profileTable_td]:[padding:5px_7px] [&_.modelInventoryTable]:[min-width:1020px] [&_.modelInventoryTable]:[table-layout:fixed] [&_.modelInventoryTable_th:first-child]:[width:16%] [&_.modelInventoryTable_th:first-child]:[min-width:178px] [&_.modelInventoryTable_td:first-child]:[width:16%] [&_.modelInventoryTable_td:first-child]:[min-width:178px] [&_.modelInventoryTable_th:nth-child(2)]:[width:14%] [&_.modelInventoryTable_th:nth-child(2)]:[min-width:150px] [&_.modelInventoryTable_td:nth-child(2)]:[width:14%] [&_.modelInventoryTable_td:nth-child(2)]:[min-width:150px] [&_.modelInventoryTable_th:nth-child(3)]:[width:22%] [&_.modelInventoryTable_th:nth-child(3)]:[min-width:220px] [&_.modelInventoryTable_td:nth-child(3)]:[width:22%] [&_.modelInventoryTable_td:nth-child(3)]:[min-width:220px] [&_.modelInventoryTable_th:nth-child(4)]:[width:11%] [&_.modelInventoryTable_th:nth-child(4)]:[min-width:116px] [&_.modelInventoryTable_td:nth-child(4)]:[width:11%] [&_.modelInventoryTable_td:nth-child(4)]:[min-width:116px] [&_.modelInventoryTable_th:nth-child(5)]:[width:26%] [&_.modelInventoryTable_th:nth-child(5)]:[min-width:230px] [&_.modelInventoryTable_td:nth-child(5)]:[width:26%] [&_.modelInventoryTable_td:nth-child(5)]:[min-width:230px] [&_.modelInventoryTable_th:nth-child(6)]:[width:11%] [&_.modelInventoryTable_th:nth-child(6)]:[min-width:120px] [&_.modelInventoryTable_td:nth-child(6)]:[width:11%] [&_.modelInventoryTable_td:nth-child(6)]:[min-width:120px] max-[720px]:[&>_.sectionText]:[white-space:normal]",
  modelLibraryTestBar:
    "vui-routes-configroute modelLibraryTestBar [display:flex] [align-items:end] [gap:8px] [flex-wrap:wrap] [padding:8px_10px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)]",
  modelLibraryTestSelect:
    "vui-routes-configroute modelLibraryTestSelect [min-width:min(360px,100%)] [flex:1_1_280px]",
  modelScenarioButtons:
    "vui-routes-configroute modelScenarioButtons [display:flex] [align-items:center] [gap:5px] [flex-wrap:wrap]",
  modelScenarioPicker:
    "vui-routes-configroute modelScenarioPicker [display:grid] [gap:6px] [margin:7px_9px_0] [&>_span]:[color:var(--fg-tertiary)] [&>_span]:[font-size:var(--vui-font-xs)] [&>_span]:[font-weight:700] [&>_span]:[text-transform:uppercase] [&>_span]:[letter-spacing:0.06em]",
  notice:
    "vui-routes-configroute notice [margin:0] [min-width:0] [color:var(--fg-secondary)] [line-height:1.38] [overflow-wrap:anywhere] [padding:7px_9px] [border-radius:8px] [border:1px_solid_var(--border-hairline)] [background:var(--vui-surface-row)]",
  noticeError:
    "vui-routes-configroute noticeError [color:var(--state-error)] [background:color-mix(in_srgb,var(--state-error)_14%,transparent)] [border-color:color-mix(in_srgb,var(--state-error)_24%,transparent)]",
  noticeSuccess:
    "vui-routes-configroute noticeSuccess [color:var(--state-success)] [background:color-mix(in_srgb,var(--accent-cool)_12%,transparent)] [border-color:color-mix(in_srgb,var(--accent-cool)_24%,transparent)]",
  page:
    "vui-routes-configroute page [--control-height:36px] [--vui-control-height-sm:36px] [--control-radius:var(--radius-control)] [--config-row-gap:10px] [--config-section-x:12px] [--config-section-y:10px] [display:grid] [grid-template-columns:clamp(15rem,16vw,17.5rem)_minmax(0,1fr)] [grid-template-rows:minmax(0,1fr)] [gap:0] [height:100%] [min-height:0] [padding:0] [overflow:hidden] [isolation:isolate] [background:var(--vui-surface-workspace)] max-[720px]:[grid-template-columns:1fr] max-[720px]:[grid-template-rows:auto_minmax(0,1fr)] max-[720px]:[height:auto] max-[720px]:[overflow:visible]",
  primaryButton:
    `vui-routes-configroute primaryButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:7px] [min-height:40px] [padding:0_16px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-sm)] [font-weight:700] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] ${primaryControl} [box-shadow:none] hover:[cursor:pointer] hover:[border-color:color-mix(in_srgb,var(--accent-warm)_40%,transparent)] hover:[background:color-mix(in_srgb,var(--accent-warm)_20%,var(--vui-control-muted))] disabled:[cursor:not-allowed] disabled:[opacity:0.56]`,
  profileGroupRow:
    `vui-routes-configroute profileGroupRow [&_td]:[padding:7px_9px] [&_td]:[color:var(--fg-secondary)] [&_td]:${vuiStateSelectedRowFillClass} [&_td]:[font-size:var(--vui-font-xs)] [&_td]:[font-weight:700]`,
  profileMetaCell:
    "vui-routes-configroute profileMetaCell [display:grid] [gap:5px] [min-width:0] [&_strong]:[min-width:0] [&_strong]:[color:var(--fg-primary)] [&_strong]:[overflow-wrap:anywhere] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[min-width:0] [&_span]:[color:var(--fg-tertiary)] [&_span]:[overflow-wrap:anywhere] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.28]",
  profileModelCell:
    "vui-routes-configroute profileModelCell [display:grid] [gap:5px] [min-width:0] [&_strong]:[min-width:0] [&_strong]:[color:var(--fg-primary)] [&_strong]:[overflow-wrap:anywhere] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[min-width:0] [&_span]:[color:var(--fg-tertiary)] [&_span]:[overflow-wrap:anywhere] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.28]",
  profileTable:
    "vui-routes-configroute profileTable [width:100%] [min-width:900px] [border-collapse:collapse] [table-layout:auto] [&_th]:[min-width:112px] [&_th]:[padding:6px_8px] [&_th]:[border-bottom:1px_solid_var(--border-hairline)] [&_th]:[text-align:left] [&_th]:[vertical-align:top] [&_td]:[min-width:112px] [&_td]:[padding:6px_8px] [&_td]:[border-bottom:1px_solid_var(--border-hairline)] [&_td]:[text-align:left] [&_td]:[vertical-align:top] [&_th:first-child]:[min-width:210px] [&_td:first-child]:[min-width:210px] [&_th]:[color:var(--fg-tertiary)] [&_th]:[font-size:var(--vui-font-xs)] [&_th]:[font-weight:700] [&_th]:[text-transform:none] [&_th]:[letter-spacing:0] [&_th]:!bg-[var(--vui-surface-row)] [&_td]:[color:var(--fg-secondary)] [&_td]:[line-height:1.28] [&_td:has(.profileTableActions)]:[min-width:150px] [&_td_>_input[type='checkbox']]:[width:16px] [&_td_>_input[type='checkbox']]:[height:16px] [&_td_>_input[type='checkbox']]:[margin-top:2px] [&_tbody_tr:last-child_td]:[border-bottom:0] [&_tbody_tr:hover]:[background:var(--vui-surface-row-hover)] [&_td.profileTaskCell]:[display:table-cell] [&_td.profileModelCell]:[display:table-cell] [&_td.profileMetaCell]:[display:table-cell] [&_td.profileTaskCell_>_:where(strong,span)]:[display:block] [&_td.profileTaskCell_>_:where(strong,span)]:[margin-bottom:3px] [&_td.profileModelCell_>_:where(strong,span)]:[display:block] [&_td.profileModelCell_>_:where(strong,span)]:[margin-bottom:3px] [&_td.profileMetaCell_>_:where(strong,span)]:[display:block] [&_td.profileMetaCell_>_:where(strong,span)]:[margin-bottom:3px] [&_td.profileTaskCell_>_:last-child]:[margin-bottom:0] [&_td.profileModelCell_>_:last-child]:[margin-bottom:0] [&_td.profileMetaCell_>_:last-child]:[margin-bottom:0] [&_td.profileTaskCell_>_.inlineBadge]:[display:inline-flex] [&_td.profileTaskCell_>_.inlineBadge]:[margin-right:5px] [&_td.profileTaskCell_>_.inlineBadge]:[margin-bottom:3px] [&_td.profileTaskCell_>_.inlineBadge]:[vertical-align:top] [&_td.profileModelCell_>_.inlineBadge]:[display:inline-flex] [&_td.profileModelCell_>_.inlineBadge]:[margin-right:5px] [&_td.profileModelCell_>_.inlineBadge]:[margin-bottom:3px] [&_td.profileModelCell_>_.inlineBadge]:[vertical-align:top] [&_td.profileMetaCell_>_.inlineBadge]:[display:inline-flex] [&_td.profileMetaCell_>_.inlineBadge]:[margin-right:5px] [&_td.profileMetaCell_>_.inlineBadge]:[margin-bottom:3px] [&_td.profileMetaCell_>_.inlineBadge]:[vertical-align:top]",
  profileTableActions:
    "vui-routes-configroute profileTableActions [display:flex] [align-items:center] [justify-content:flex-start] [gap:5px] [flex-wrap:wrap]",
  profileTableSelect:
    "vui-routes-configroute profileTableSelect [min-width:220px]",
  profileTableWrap:
    "vui-routes-configroute profileTableWrap [width:100%] [min-width:0] [overflow-x:auto] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-row)] [scrollbar-gutter:stable]",
  profileTaskCell:
    "vui-routes-configroute profileTaskCell [display:grid] [gap:5px] [min-width:0] [&_strong]:[min-width:0] [&_strong]:[color:var(--fg-primary)] [&_strong]:[overflow-wrap:anywhere] [&_strong]:[font-size:var(--vui-font-xs)] [&_span]:[min-width:0] [&_span]:[color:var(--fg-tertiary)] [&_span]:[overflow-wrap:anywhere] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.28]",
  quickActionItem:
    "vui-routes-configroute quickActionItem [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-row)] [display:grid] [grid-template-columns:minmax(0,1fr)_auto] [align-items:center] [gap:10px] [padding:11px] [color:inherit] [text-decoration:none] hover:[border-color:color-mix(in_srgb,var(--accent-warm)_32%,transparent)] hover:[background:var(--vui-surface-row-hover)] [&_div]:[display:grid] [&_div]:[gap:6px] [&_div]:[min-width:0] [&_strong]:[overflow-wrap:anywhere] [&_small]:[overflow-wrap:anywhere] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:0.9rem] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.45]",
  quickActionList:
    "vui-routes-configroute quickActionList [display:grid] [gap:10px]",
  rawConfigPanel:
    "vui-routes-configroute rawConfigPanel [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[line-height:1.38] [display:grid] [gap:6px] [padding:7px_8px] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-row)] [&_summary]:[cursor:pointer] [&_summary]:[color:var(--fg-primary)] [&_summary]:[font-weight:600]",
  rawToml:
    "vui-routes-configroute rawToml [overflow:auto] [overflow-wrap:anywhere] [font-family:Consolas,'SFMono-Regular',monospace] [font-size:var(--vui-font-xs)] [margin:0] [padding:8px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] [background:var(--vui-surface-workspace)] [color:var(--fg-secondary)] [line-height:1.55]",
  readonlyCodeField:
    "vui-routes-configroute readonlyCodeField [display:flex] [align-items:center] [min-height:var(--control-height)] [width:100%] [min-width:0] [padding:6px_8px] [border:1px_solid_var(--border-hairline)] [border-radius:var(--control-radius)] [background:var(--vui-surface-workspace)] [color:var(--fg-secondary)] [font-family:var(--font-mono)] [font-size:var(--vui-font-xs)] [line-height:1.25] [overflow-wrap:anywhere]",
  returnButton:
    "vui-routes-configroute returnButton [display:inline-flex] [align-items:center] [justify-self:start] [gap:5px] [min-height:27px] [max-width:100%] [padding:0_8px] [border:1px_solid_var(--border-hairline)] [border-radius:var(--control-radius)] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [font-weight:700] [text-decoration:none] hover:[border-color:var(--border-strong)] hover:[color:var(--fg-primary)] hover:[background:var(--vui-surface-row-hover)] [&_svg]:[transform:rotate(180deg)]",
  sectionHeader:
    `vui-routes-configroute sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] ${sectionHeaderSurface}`,
  sectionHeaderActions:
    "vui-routes-configroute sectionHeaderActions [display:flex] [align-items:center] [justify-content:end] [gap:6px] [flex-wrap:wrap]",
  sectionHeaderMain:
    "vui-routes-configroute sectionHeaderMain [display:grid] [gap:3px] [min-width:0]",
  sectionHeaderMeta:
    "vui-routes-configroute sectionHeaderMeta [display:inline-flex] [align-items:center] [gap:6px] [min-height:28px] [padding:0_8px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_86%,transparent)] [border-radius:999px] [background:var(--vui-control-muted)]",
  sectionHeaderMetaLabel:
    "vui-routes-configroute sectionHeaderMetaLabel [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.06em]",
  sectionIcon:
    "vui-routes-configroute sectionIcon [color:var(--fg-tertiary)] [flex:0_0_auto]",
  sectionLink:
    "vui-routes-configroute sectionLink [display:inline-flex] [align-items:center] [justify-content:space-between] [gap:6px] [min-height:27px] [padding:0_8px] [border:1px_solid_var(--border-hairline)] [border-radius:var(--control-radius)] [background:transparent] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [font-weight:500] [font-family:inherit] [text-decoration:none] [text-align:left] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] [&_span:first-child]:[overflow:hidden] [&_span:first-child]:[text-overflow:ellipsis] [&_span:first-child]:[white-space:nowrap] hover:[border-color:color-mix(in_srgb,var(--accent-warm)_26%,transparent)] hover:[background:var(--vui-surface-row-hover)] hover:[color:var(--fg-primary)] hover:[cursor:pointer] max-[1120px]:[width:auto] max-[1120px]:[max-width:230px] max-[1120px]:[flex:0_1_auto] max-[720px]:[max-width:none]",
  sectionLinkActive:
    `vui-routes-configroute sectionLinkActive ${activeControl}`,
  sectionNav:
    "vui-routes-configroute sectionNav [display:grid] [align-content:start] [gap:4px] [overflow:visible] [padding-right:4px] max-[1120px]:[display:flex] max-[1120px]:[flex-wrap:wrap] max-[1120px]:[gap:6px] max-[1120px]:[padding-right:0] max-[720px]:[display:grid] max-[720px]:[grid-template-columns:1fr]",
  sectionSurface:
    `vui-routes-configroute sectionSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.sectionText]:[padding:6px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-xs)] [&>_:where(_.hashGrid,.matrixGrid,.healthSummaryGrid,.logHelperGrid,.toggleGrid,.healthWorkbenchGrid,.profileTableWrap,.formSurface,.actionsRow,.rawConfigPanel,.editorWrap,.agentRunPanel_)]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.sectionText_+_:where(_.hashGrid,.matrixGrid,.healthSummaryGrid,.logHelperGrid,.toggleGrid,.healthWorkbenchGrid,.profileTableWrap,.formSurface,.actionsRow,.rawConfigPanel,.editorWrap_)]:[margin-top:6px]`,
  sectionText:
    "vui-routes-configroute sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle:
    "vui-routes-configroute sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:0.92rem] [line-height:1.15]",
  sectionToolbarGroup:
    "vui-routes-configroute sectionToolbarGroup [display:inline-flex] [align-items:center] [gap:4px] [padding:3px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_86%,transparent)] [border-radius:999px] [background:var(--vui-surface-toolbar)] [flex-wrap:wrap] [justify-content:end]",
  segmentButton:
    `vui-routes-configroute segmentButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:6px] [min-height:var(--control-height)] [padding:0_9px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-xs)] [font-weight:600] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] ${mutedControl} hover:[cursor:pointer] disabled:[cursor:not-allowed] disabled:[opacity:0.56] [min-height:27px] [border:0] [background:transparent] [color:var(--fg-secondary)]`,
  segmentButtonActive:
    "vui-routes-configroute segmentButtonActive [background:color-mix(in_srgb,var(--accent-warm)_16%,transparent)] [color:var(--accent-warm-2)]",
  segmented:
    "vui-routes-configroute segmented [display:inline-flex] [align-items:center] [gap:4px] [padding:3px] [border:1px_solid_var(--border-soft)] [border-radius:999px] [background:var(--vui-control-muted)] [flex-wrap:wrap]",
  sidebar:
    `vui-routes-configroute sidebar ${readablePanelSurface} [position:sticky] [top:0] [display:flex] [flex-direction:column] [gap:var(--config-row-gap)] [padding:8px] [min-height:360px] [max-height:calc(100dvh_-_28px)] [overflow-x:hidden] [overflow-y:auto] [overscroll-behavior:contain] [scrollbar-gutter:stable] max-[1120px]:[position:static] max-[1120px]:[min-height:0] max-[1120px]:[height:auto!important] max-[1120px]:[max-height:none] max-[1120px]:[overflow:visible]`,
  sidebarIntro:
    "vui-routes-configroute sidebarIntro [display:grid] [gap:5px] [&_.subtitle]:[display:-webkit-box] [&_.subtitle]:[overflow:hidden] [&_.subtitle]:[font-size:var(--route-topbar-subtitle-size)] [&_.subtitle]:[-webkit-box-orient:vertical] [&_.subtitle]:[-webkit-line-clamp:2]",
  sidebarMetrics:
    "vui-routes-configroute sidebarMetrics [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [gap:6px] max-[720px]:[grid-template-columns:1fr]",
  sidebarMetaStrip:
    "vui-routes-configroute sidebarMetaStrip [display:flex] [align-items:center] [gap:5px] [flex-wrap:wrap] [padding-top:1px]",
  sidebarNavPanel:
    "vui-routes-configroute sidebarNavPanel [display:flex] [flex-direction:column] [gap:6px] [padding-top:1px] [border-top:1px_solid_var(--border-hairline)] max-[1120px]:[&:not(.sidebarNavPanelCollapsed)]:[display:grid] max-[1120px]:[&:not(.sidebarNavPanelCollapsed)]:[grid-template-columns:minmax(170px,0.32fr)_minmax(0,1fr)] max-[1120px]:[&:not(.sidebarNavPanelCollapsed)]:[align-items:start] max-[1120px]:[&:not(.sidebarNavPanelCollapsed)]:[gap:6px_10px] max-[720px]:[&:not(.sidebarNavPanelCollapsed)]:[grid-template-columns:1fr]",
  sidebarNavPanelCollapsed:
    "vui-routes-configroute sidebarNavPanelCollapsed [flex:0_0_auto]",
  sidebarPanelActions:
    "vui-routes-configroute sidebarPanelActions [display:flex] [align-items:center] [gap:4px] [flex-wrap:wrap] [justify-content:end]",
  sidebarPanelHeader:
    "vui-routes-configroute sidebarPanelHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:6px]",
  sidebarPanelIntro:
    "vui-routes-configroute sidebarPanelIntro [display:grid] [gap:1px] [min-width:0]",
  sidebarPanelToggle:
    "vui-routes-configroute sidebarPanelToggle [flex:0_0_auto]",
  sidebarResizeCorner:
    "vui-routes-configroute sidebarResizeCorner [position:absolute] [z-index:3] [opacity:0.34] [transition:opacity_140ms_ease,background-color_140ms_ease] hover:[opacity:0.88] hover:[background:color-mix(in_srgb,var(--accent-warm)_20%,transparent)] [right:0] [bottom:0] [width:18px] [height:18px] [cursor:nwse-resize] [border-radius:999px_0_8px_0] !bg-[var(--vui-surface-row)] max-[1120px]:[display:none]",
  sidebarResizeX:
    "vui-routes-configroute sidebarResizeX [position:absolute] [z-index:3] [opacity:0.34] [transition:opacity_140ms_ease,background-color_140ms_ease] hover:[opacity:0.88] hover:[background:color-mix(in_srgb,var(--accent-warm)_20%,transparent)] [top:18px] [right:0] [width:10px] [height:calc(100%_-_34px)] [cursor:col-resize] [background:var(--vui-gradient-route-soft)] max-[1120px]:[display:none]",
  sidebarResizeY:
    "vui-routes-configroute sidebarResizeY [position:absolute] [z-index:3] [opacity:0.34] [transition:opacity_140ms_ease,background-color_140ms_ease] hover:[opacity:0.88] hover:[background:color-mix(in_srgb,var(--accent-warm)_20%,transparent)] [left:18px] [bottom:0] [width:calc(100%_-_36px)] [height:10px] [cursor:row-resize] [background:var(--vui-gradient-route-soft)] max-[1120px]:[display:none]",
  sidebarStatus:
    "vui-routes-configroute sidebarStatus [display:grid] [gap:5px] [padding:8px] [border:1px_solid_var(--border-hairline)] [border-radius:8px] !bg-[var(--vui-surface-row)] max-[1120px]:[grid-template-columns:minmax(150px,0.7fr)_minmax(180px,1fr)_max-content] max-[1120px]:[align-items:center] max-[1120px]:[&_.buttonBlock]:[width:auto] max-[1120px]:[&_.buttonBlock]:[justify-self:end] max-[1120px]:[&>_.helperText]:[grid-column:1/-1] max-[720px]:[grid-template-columns:1fr] max-[720px]:[&_.buttonBlock]:[width:100%] max-[720px]:[&_.buttonBlock]:[justify-self:stretch]",
  sidebarStatusCompact:
    `vui-routes-configroute sidebarStatusCompact ${readableRowSurface} [display:grid] [gap:5px] [padding:8px]`,
  sidebarStatusGrid:
    "vui-routes-configroute sidebarStatusGrid [display:grid] [grid-template-columns:minmax(0,1fr)_minmax(72px,auto)] [gap:5px] [&_span]:[display:grid] [&_span]:[gap:2px] [&_span]:[min-width:0] [&_span]:[padding:6px_7px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:7px] [&_span]:[background:var(--vui-surface-row)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[line-height:1.15] [&_strong]:[min-width:0] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[line-height:1.25] [&_strong]:[overflow-wrap:anywhere] max-[1120px]:[grid-template-columns:repeat(2,minmax(96px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  sidebarStatusHeader:
    "vui-routes-configroute sidebarStatusHeader [display:flex] [align-items:center] [justify-content:space-between] [gap:6px] [&>_span:first-child]:[min-width:0] [&>_span:first-child]:[color:var(--fg-tertiary)] [&>_span:first-child]:[font-size:var(--vui-font-xs)] [&>_span:first-child]:[font-weight:700] [&>_span:first-child]:[text-transform:uppercase] [&>_span:first-child]:[letter-spacing:0.06em] [&>_span:first-child]:[overflow:hidden] [&>_span:first-child]:[text-overflow:ellipsis] [&>_span:first-child]:[white-space:nowrap] max-[1120px]:[min-width:0]",
  statusBadge:
    "vui-routes-configroute statusBadge [display:inline-flex] [align-items:center] [justify-content:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [border:1px_solid_transparent] [font-size:var(--vui-font-xs)] [white-space:nowrap] [color:var(--fg-secondary)] [background:var(--vui-surface-row)]",
  statusBadgePending:
    "vui-routes-configroute statusBadgePending [color:var(--accent-warm-2)] [background:color-mix(in_srgb,var(--accent-warm)_12%,transparent)] [border-color:color-mix(in_srgb,var(--accent-warm)_22%,transparent)]",
  statusBadgeReady:
    "vui-routes-configroute statusBadgeReady [color:var(--state-success)] [background:color-mix(in_srgb,var(--accent-cool)_14%,transparent)] [border-color:color-mix(in_srgb,var(--accent-cool)_26%,transparent)]",
  subtitle:
    "vui-routes-configroute subtitle [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  summaryBarWarning:
    "vui-routes-configroute summaryBarWarning",
  themeBackgroundDropButton:
    "vui-routes-configroute themeBackgroundDropButton [position:relative] [display:block] [min-width:0] [border-radius:6px] [cursor:pointer] [&:hover_.themeBackgroundImagePreview]:[border-color:color-mix(in_srgb,var(--accent-warm)_34%,var(--border-hairline))] [&:hover_.themeBackgroundImagePreview]:[background:color-mix(in_srgb,var(--accent-warm)_9%,var(--vui-surface-row))] [&:hover_.themeBackgroundImagePlaceholder]:[border-color:color-mix(in_srgb,var(--accent-warm)_34%,var(--border-hairline))] [&:hover_.themeBackgroundImagePlaceholder]:[background:color-mix(in_srgb,var(--accent-warm)_9%,var(--vui-surface-row))] [&_input]:[position:absolute] [&_input]:[inset:0] [&_input]:[opacity:0] [&_input]:[pointer-events:none]",
  themeBackgroundImageActions:
    "vui-routes-configroute themeBackgroundImageActions [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [align-items:center] [gap:6px]",
  themeBackgroundImageCard:
    "vui-routes-configroute themeBackgroundImageCard [grid-column:1/-1] [grid-template-columns:1fr] [align-content:start] [min-height:0] [padding:9px]",
  themeBackgroundImageEditor:
    "vui-routes-configroute themeBackgroundImageEditor [display:grid] [grid-template-columns:minmax(0,0.34fr)_minmax(0,1fr)] [gap:12px] [align-items:start] [min-width:0] max-[900px]:[grid-template-columns:1fr]",
  themeBackgroundImageMeta:
    "vui-routes-configroute themeBackgroundImageMeta [display:grid] [align-content:space-between] [gap:6px] [min-width:0] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&>_span]:[min-width:0] [&>_span]:[overflow:hidden] [&>_span]:[color:var(--fg-tertiary)] [&>_span]:[font-family:var(--font-mono)] [&>_span]:[font-size:var(--vui-font-xs)] [&>_span]:[text-overflow:ellipsis] [&>_span]:[white-space:nowrap]",
  themeBackgroundImagePlaceholder:
    "vui-routes-configroute themeBackgroundImagePlaceholder [width:100%] [aspect-ratio:16/9] [min-height:104px] [border:1px_solid_var(--border-hairline)] [border-radius:6px] [background:var(--vui-surface-row)] [display:grid] [place-items:center] [color:var(--fg-tertiary)]",
  themeBackgroundImagePreview:
    "vui-routes-configroute themeBackgroundImagePreview [width:100%] [aspect-ratio:16/9] [min-height:104px] [border:1px_solid_var(--border-hairline)] [border-radius:6px] [background:var(--vui-surface-row)] [object-fit:cover]",
  themeBackgroundImageValue:
    "vui-routes-configroute themeBackgroundImageValue [display:grid] [grid-template-columns:1fr] [align-items:start] [gap:7px] [min-width:0] [max-width:100%] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [overflow-wrap:anywhere] max-[720px]:[grid-template-columns:1fr]",
  themeBackgroundPresetButton:
    "vui-routes-configroute themeBackgroundPresetButton [position:relative] [display:grid] [grid-template-rows:minmax(68px,auto)_auto] [gap:6px] [min-width:0] [min-height:0] [padding:6px] [border:1px_solid_var(--border-hairline)] [border-radius:6px] !bg-[var(--vui-surface-row)] [color:var(--fg-secondary)] [cursor:pointer] [text-align:left] hover:[border-color:color-mix(in_srgb,var(--accent-warm)_36%,var(--border-hairline))] hover:[background:color-mix(in_srgb,var(--accent-warm)_9%,var(--vui-surface-row))] disabled:[cursor:not-allowed] disabled:[opacity:0.6] [&[data-active='true']]:[border-color:color-mix(in_srgb,var(--accent-warm)_62%,var(--border-strong))] [&[data-active='true']]:[background:color-mix(in_srgb,var(--accent-warm)_12%,var(--vui-surface-row))] [&[data-active='true']]:[box-shadow:var(--vui-shadow-inset-accent)] [&_img]:[width:100%] [&_img]:[aspect-ratio:16/9] [&_img]:[height:auto] [&_img]:[border-radius:4px] [&_img]:[object-fit:cover] [&>_span]:[min-width:0] [&>_span]:[overflow:hidden] [&>_span]:[color:var(--fg-secondary)] [&>_span]:[font-size:var(--vui-font-xs)] [&>_span]:[font-weight:700] [&>_span]:[line-height:1.2] [&>_span]:[text-overflow:ellipsis] [&>_span]:[white-space:nowrap] [&>_em]:[position:absolute] [&>_em]:[top:9px] [&>_em]:[right:9px] [&>_em]:[padding:2px_6px] [&>_em]:[border:1px_solid_color-mix(in_srgb,var(--accent-warm)_40%,transparent)] [&>_em]:[border-radius:999px] [&>_em]:!bg-[var(--vui-surface-panel)] [&>_em]:[color:var(--fg-primary)] [&>_em]:[font-size:var(--vui-font-xs)] [&>_em]:[font-style:normal] [&>_em]:[font-weight:800] [&>_em]:[line-height:1.2]",
  themeBackgroundPresetGrid:
    "vui-routes-configroute themeBackgroundPresetGrid [display:grid] [grid-template-columns:repeat(auto-fill,minmax(132px,1fr))] [gap:8px] max-[720px]:[grid-template-columns:repeat(auto-fill,minmax(118px,1fr))]",
  themeBackgroundPresetPanel:
    "vui-routes-configroute themeBackgroundPresetPanel [display:grid] [gap:8px] [min-width:0]",
  themeBackgroundPresetTitle:
    "vui-routes-configroute themeBackgroundPresetTitle [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:700] [letter-spacing:0]",
  title:
    "vui-routes-configroute title [margin:0] [font-family:var(--font-body)] [font-weight:760] [font-size:var(--route-topbar-title-size)] [line-height:1.1]",
  toggleField:
    "vui-routes-configroute toggleField [display:grid] [gap:4px] [&_span]:[overflow-wrap:anywhere] [&>_span]:[color:var(--fg-tertiary)] [&>_span]:[font-size:var(--vui-font-xs)] [display:flex] [align-items:center] [min-height:var(--control-height)] [padding:6px_8px] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [&_input]:[width:16px] [&_input]:[height:16px]",
  toggleGrid:
    "vui-routes-configroute toggleGrid [display:grid] [gap:8px] [grid-template-columns:repeat(auto-fit,minmax(168px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  toolbarButton:
    "vui-routes-configroute toolbarButton [border-radius:999px]",
  treeBody:
    "vui-routes-configroute treeBody [display:grid] [gap:8px]",
  treeFieldCard:
    "vui-routes-configroute treeFieldCard [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_92%,transparent)] [border-radius:7px] [background:var(--vui-surface-row)] [display:grid] [gap:4px] [padding:6px]",
  treeFieldCardEdit:
    "vui-routes-configroute treeFieldCardEdit [align-content:start] [gap:10px] [min-height:56px] [padding:12px]",
  treeFieldCardView:
    "vui-routes-configroute treeFieldCardView [grid-template-columns:minmax(12rem,0.34fr)_minmax(0,1fr)] [align-items:start] [gap:8px_16px] [min-height:56px] [padding:12px] [&_.treeFieldHead]:[min-width:0] [&_.treeFieldHead]:[justify-content:start] [&_.treeFieldHead]:[gap:6px] [&_.treeFieldLabel]:[overflow:hidden] [&_.treeFieldLabel]:[text-overflow:ellipsis] [&_.treeFieldLabel]:[white-space:nowrap] [&_.treeFieldLabel]:[font-size:var(--vui-font-sm)] [&_.treeHint]:[display:-webkit-box] [&_.treeHint]:[overflow:hidden] [&_.treeHint]:[-webkit-box-orient:vertical] [&_.treeHint]:[grid-column:1/-1] [&_.treeHint]:[grid-row:2] [&_.treeHint]:[-webkit-line-clamp:2] [&_.treeFieldValue]:[grid-column:2] [&_.treeFieldValue]:[grid-row:1] [&_.treeFieldValue]:[min-width:0] [&_.treeFieldValue]:[width:100%] [&_.treeFieldValue]:[min-height:40px] [&_.treeFieldValue]:[padding:9px_12px] [&_.treeFieldValue]:[border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_90%,transparent)] [&_.treeFieldValue]:[border-radius:var(--control-radius)] [&_.treeFieldValue]:[background:color-mix(in_srgb,var(--vui-surface-workspace)_92%,var(--vui-surface-panel))] [&_.treeFieldValue]:[font-family:var(--font-mono)]",
  treeFieldHead:
    "vui-routes-configroute treeFieldHead [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [align-items:center]",
  treeFieldLabel:
    "vui-routes-configroute treeFieldLabel [color:var(--fg-primary)] [font-size:var(--vui-font-xs)] [font-weight:600]",
  treeFieldValue:
    "vui-routes-configroute treeFieldValue [color:var(--fg-secondary)] [overflow-wrap:anywhere] [line-height:1.34] [font-size:var(--vui-font-xs)] [background:color-mix(in_srgb,var(--vui-surface-workspace)_92%,var(--vui-surface-panel))]",
  treeGrid:
    "vui-routes-configroute treeGrid [display:grid] [gap:7px] [grid-template-columns:repeat(2,minmax(0,1fr))] [align-items:start] max-[1120px]:[grid-template-columns:repeat(2,minmax(210px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  treeHint:
    "vui-routes-configroute treeHint [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [line-height:1.35]",
  treeNestedBlock:
    "vui-routes-configroute treeNestedBlock [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-row)] [display:grid] [gap:5px] [padding:7px]",
  treeNestedHeader:
    "vui-routes-configroute treeNestedHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:600]",
  treeObjectBlock:
    "vui-routes-configroute treeObjectBlock [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-row)] [display:grid] [gap:5px] [padding:7px]",
  treeObjectCell:
    "vui-routes-configroute treeObjectCell [min-width:0] [&_.treeObjectBlock]:[min-height:42px] [&_.treeNestedBlock]:[min-height:42px] [&_.treeToggle]:[min-height:34px] [&_.treeToggle_.treeHint]:[display:none]",
  treeObjectHeader:
    "vui-routes-configroute treeObjectHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px]",
  treeStack:
    "vui-routes-configroute treeStack [display:grid] [gap:6px]",
  treeToggle:
    "vui-routes-configroute treeToggle [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [width:100%] [min-height:30px] [padding:0] [border:0] [background:transparent] [color:inherit] [text-align:left] hover:[cursor:pointer] [&_.cardTitle]:[overflow:hidden] [&_.cardTitle]:[text-overflow:ellipsis] [&_.cardTitle]:[white-space:nowrap] [&_.treeHint]:[display:-webkit-box] [&_.treeHint]:[overflow:hidden] [&_.treeHint]:[-webkit-box-orient:vertical] [&_.treeHint]:[-webkit-line-clamp:1]",
  treeToggleIcon:
    "vui-routes-configroute treeToggleIcon [color:var(--fg-tertiary)] [flex:0_0_auto] [transition:transform_140ms_ease]",
  treeToggleIconExpanded:
    "vui-routes-configroute treeToggleIconExpanded [color:var(--fg-tertiary)] [flex:0_0_auto] [transition:transform_140ms_ease] [transform:rotate(90deg)]",
  treeToggleLabel:
    "vui-routes-configroute treeToggleLabel [display:flex] [align-items:center] [gap:6px] [min-width:0] [&>_div]:[display:grid] [&>_div]:[gap:2px] [&>_div]:[min-width:0]",
  treeWide:
    "vui-routes-configroute treeWide [grid-column:1/-1]",
  toolingMetaPanel:
    "vui-routes-configroute toolingMetaPanel [display:flex] [align-items:center] [justify-content:space-between] [gap:12px] [min-width:0] [&_[data-vui=status-strip]]:[flex:1_1_auto]",
  userProfileAvatarFields:
    "vui-routes-configroute userProfileAvatarFields [display:grid] [gap:6px] [min-width:0] [grid-template-columns:repeat(2,minmax(0,1fr))] [&_.treeFieldCardView]:![grid-template-columns:minmax(132px,0.44fr)_minmax(0,1fr)] [&_.treeFieldCardView_.treeHint]:[display:none] max-[900px]:[grid-template-columns:1fr]",
  userProfileAvatarGroup:
    "vui-routes-configroute userProfileAvatarGroup [min-width:0] [display:grid] [gap:6px]",
  userProfileAvatarHeader:
    "vui-routes-configroute userProfileAvatarHeader [display:flex] [align-items:center] [justify-content:space-between] [gap:12px] [min-width:0] [padding:0_2px] [&_strong]:[flex:0_0_auto] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:700] [&_strong]:[line-height:1.2] [&_span]:[min-width:0] [&_span]:[overflow:hidden] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.25] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] max-[720px]:[align-items:start] max-[720px]:[flex-direction:column] max-[720px]:[gap:3px] max-[720px]:[&_span]:[white-space:normal]",
  userProfileIdentityFields:
    "vui-routes-configroute userProfileIdentityFields [display:grid] [gap:6px] [min-width:0] [grid-template-columns:minmax(0,1fr)]",
  userProfileLayout:
    "vui-routes-configroute userProfileLayout [display:grid] [gap:7px] [&_.treeFieldCardView_.treeHint]:[-webkit-line-clamp:1]",
  userProfilePrimaryGrid:
    "vui-routes-configroute userProfilePrimaryGrid [display:grid] [align-items:start] [gap:8px] [min-width:0] [grid-template-columns:minmax(240px,0.38fr)_minmax(0,0.62fr)] max-[900px]:[grid-template-columns:1fr]",
  userProfileAdvancedFields:
    "vui-routes-configroute userProfileAdvancedFields [display:grid] [gap:6px] [min-width:0] [grid-template-columns:minmax(0,1fr)]",
} as const;

export default styles;
