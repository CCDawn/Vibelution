// Wave 8 prune: removed 100 unused keys (ConfigRoute panel-componentization residue).
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
  cardTitle:
    "vui-routes-configroute cardTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:0.96rem] [font-weight:600] [min-width:0] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  compactButton:
    "vui-routes-configroute compactButton [min-height:27px] [padding:0_8px] [font-size:var(--vui-font-xs)]",
  configProgressiveBody:
    "vui-routes-configroute configProgressiveBody grid min-w-0 w-full max-w-[72rem] gap-5 px-4 py-4",
  configCompactPathProgressiveBody:
    "vui-routes-configroute configCompactPathProgressiveBody gap-4",
  configCompactAdvancedProgressiveBody:
    "vui-routes-configroute configCompactAdvancedProgressiveBody gap-4",
  configAdvancedGrid:
    "vui-routes-configroute configAdvancedGrid grid-cols-1",
  configTier:
    "vui-routes-configroute configTier [display:grid] [gap:7px] [min-width:0]",
  configTierHeader:
    "vui-routes-configroute configTierHeader [display:flex] [align-items:center] [justify-content:space-between] [gap:12px] [min-width:0] [padding:2px_2px_0]",
  configTierHeaderCopy:
    "vui-routes-configroute configTierHeaderCopy [display:grid] [gap:3px] [min-width:0] [text-align:left] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_strong]:[font-weight:700] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.35] [&_span]:[overflow-wrap:anywhere]",
  configAdvancedTier:
    "vui-routes-configroute configAdvancedTier [padding-top:10px] [border-top:1px_solid_var(--border-hairline)]",
  configAdvancedToggle:
    "vui-routes-configroute configAdvancedToggle !flex w-full !justify-between !items-center gap-4 !border-0 !bg-transparent !px-0 !py-3 text-left",
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
    "vui-routes-configroute configHeader min-w-0 !border-0 !rounded-none !shadow-none !bg-vui-surface-panel [&>[data-vui=route-header]]:!border-0 [&>[data-vui=route-header]]:!rounded-none [&>[data-vui=route-header]]:!shadow-none [&>[data-vui=route-header]]:!bg-transparent [&>[data-vui=route-header]]:!py-2 [&>[data-vui=route-header]]:!px-3",
  configStatusMeta:
    "vui-routes-configroute configStatusMeta [display:flex] [align-items:center] [gap:6px] [flex-wrap:wrap] [min-width:0]",
  configStatusPath:
    "vui-routes-configroute configStatusPath [display:inline-flex] [align-items:center] [min-height:24px] [max-width:100%] [padding:0_8px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [background:var(--vui-surface-workspace)] [color:var(--fg-secondary)] [font-family:var(--font-mono)] [font-size:var(--vui-font-xs)] [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]",
  configToolbar:
    "vui-routes-configroute configToolbar grid min-w-0 gap-2 border-b border-[var(--vui-border-subtle)] !bg-vui-surface-panel px-3 py-2",
  content:
    "vui-routes-configroute content !flex min-h-0 min-w-0 h-full flex-col overflow-hidden !bg-vui-surface-panel",
  pageViewport:
    "vui-routes-configroute pageViewport [display:grid] [align-content:start] [gap:12px] min-w-0 min-h-0 overflow-y-auto overflow-x-hidden [padding:12px] [scrollbar-gutter:stable] [&:has(>_.providerModelsLayout)]:[align-content:stretch] [&:has(>_.providerModelsLayout)]:[grid-template-rows:minmax(0,1fr)] [&:has(>_.notice):has(>_.providerModelsLayout)]:[grid-template-rows:auto_minmax(0,1fr)]",
  contentModels:
    "vui-routes-configroute contentModels [align-content:stretch] [grid-template-rows:minmax(0,1fr)_auto] [height:100%] [max-height:calc(100dvh_-_76px)] [min-width:0] [&:has(>_.notice)]:[grid-template-rows:auto_minmax(0,1fr)_auto] [&>_.configDiscoverySection:last-child]:[display:grid] [&>_.configDiscoverySection:last-child]:[grid-template-rows:auto_auto] max-[720px]:[max-height:none] max-[720px]:[height:auto] max-[720px]:[overflow:visible]",
  providerModelsLayout:
    "vui-routes-configroute providerModelsLayout flex flex-col h-full min-h-0 min-w-0 gap-4 overflow-y-auto overflow-x-hidden [&>#config-models]:flex-1 [&>#config-models]:min-h-[28rem]",
  providerModeButton:
    "vui-routes-configroute providerModeButton min-h-8 self-start px-3.5 [font-size:var(--vui-font-sm)] font-semibold",
  providerRouteEditSurface:
    "vui-routes-configroute providerRouteEditSurface grid min-w-0 gap-2",
  providerRouteEditGrid:
    "vui-routes-configroute providerRouteEditGrid grid min-w-0 grid-cols-2 gap-4 [&>label:first-child]:col-span-full",
  providerRouteEditField:
    "vui-routes-configroute providerRouteEditField grid min-w-0 gap-1",
  providerRouteEditWarning:
    "vui-routes-configroute providerRouteEditWarning m-0 [font-size:var(--vui-font-xs)] text-[var(--state-warning)]",
  dangerButton:
    `vui-routes-configroute dangerButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:7px] [min-height:40px] [padding:0_14px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-sm)] [font-weight:650] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] ${mutedControl} [color:var(--state-error)] [border-color:color-mix(in_srgb,var(--state-error)_24%,transparent)] [background:color-mix(in_srgb,var(--state-error)_12%,var(--vui-control-muted))] hover:[cursor:pointer] hover:[border-color:color-mix(in_srgb,var(--state-error)_36%,transparent)] disabled:[cursor:not-allowed] disabled:[opacity:0.56]`,
  eyebrow:
    "vui-routes-configroute eyebrow [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [text-transform:uppercase] [letter-spacing:0.08em]",
  field:
    "vui-routes-configroute field [display:grid] [grid-template-columns:minmax(12rem,0.34fr)_minmax(0,1fr)] [align-items:start] [gap:10px_16px] [&_span]:[overflow-wrap:anywhere] [&>_span]:[padding-top:10px] [&>_span]:[color:var(--fg-secondary)] [&>_span]:[font-size:var(--vui-font-sm)] [&>_span]:[font-weight:650] [&_input]:[width:100%] [&_input]:[min-width:0] [&_input]:[border:1px_solid_var(--border-soft)] [&_input]:[border-radius:var(--control-radius)] [&_input]:[background:var(--vui-surface-workspace)] [&_input]:[color:var(--fg-primary)] [&_input]:[padding:8px_12px] [&_input]:[font:inherit] [&_input]:[font-size:var(--vui-font-sm)] [&_select]:[width:100%] [&_select]:[min-width:0] [&_select]:[border:1px_solid_var(--border-soft)] [&_select]:[border-radius:var(--control-radius)] [&_select]:[background:var(--vui-surface-workspace)] [&_select]:[color:var(--fg-primary)] [&_select]:[padding:8px_12px] [&_select]:[font:inherit] [&_select]:[font-size:var(--vui-font-sm)] [&_textarea]:[width:100%] [&_textarea]:[min-width:0] [&_textarea]:[border:1px_solid_var(--border-soft)] [&_textarea]:[border-radius:var(--control-radius)] [&_textarea]:[background:var(--vui-surface-workspace)] [&_textarea]:[color:var(--fg-primary)] [&_textarea]:[padding:10px_12px] [&_textarea]:[font:inherit] [&_textarea]:[font-size:var(--vui-font-sm)] [&_input]:[min-height:var(--control-height)] [&_select]:[min-height:var(--control-height)]",
  fileUploadButton:
    "vui-routes-configroute fileUploadButton [position:relative] [overflow:hidden] [cursor:pointer] [&_input]:[position:absolute] [&_input]:[inset:0] [&_input]:[opacity:0] [&_input]:[pointer-events:none]",
  helperText:
    "vui-routes-configroute helperText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  inlineBadge:
    "vui-routes-configroute inlineBadge [display:inline-flex] [align-items:center] [justify-content:center] [min-height:24px] [padding:0_8px] [border-radius:999px] [border:1px_solid_transparent] [font-size:var(--vui-font-xs)] [white-space:nowrap] [color:var(--fg-secondary)] [background:var(--vui-surface-row)]",
  inlineError:
    "vui-routes-configroute inlineError [margin:0] [color:var(--state-error)] [font-size:var(--vui-font-xs)] [line-height:1.35]",
  leaveGuardPanel:
    "vui-routes-configroute leaveGuardPanel w-[min(520px,100%)]",
  loadingBoard:
    `vui-routes-configroute loadingBoard ${panelSurface} [display:grid] [grid-template-rows:auto_auto_minmax(0,1fr)] [align-content:start] [gap:8px] [padding:10px] [min-width:0] [overflow:hidden]`,
  loadingMetricGrid:
    "vui-routes-configroute loadingMetricGrid [&_strong]:[display:block] [&_strong]:[border-radius:6px] [&_strong]:[background:var(--vui-gradient-route-soft)] [display:grid] [grid-template-columns:repeat(4,minmax(0,1fr))] [gap:7px] [&_span]:[display:grid] [&_span]:[gap:5px] [&_span]:[min-height:54px] [&_span]:[padding:8px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:8px] [&_span]:[background:var(--vui-surface-row)] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] [&_small]:[text-transform:uppercase] [&_strong]:[min-height:16px]",
  loadingNavList:
    "vui-routes-configroute loadingNavList [display:grid] [gap:5px] [margin-top:4px] [&_span]:[display:flex] [&_span]:[align-items:center] [&_span]:[min-height:27px] [&_span]:[padding:0_8px] [&_span]:[border:1px_solid_var(--border-hairline)] [&_span]:[border-radius:var(--control-radius)] [&_span]:[color:var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[background:var(--vui-surface-row)] [&_.loadingNavActive]:[border-color:color-mix(in_srgb,var(--accent-cool)_32%,transparent)] [&_.loadingNavActive]:[background:color-mix(in_srgb,var(--accent-cool)_10%,transparent)] [&_.loadingNavActive]:[color:var(--accent-warm-2)]",
  loadingNavPanel:
    `vui-routes-configroute loadingNavPanel ${panelSurface} [display:grid] [align-content:start] [gap:8px] [padding:10px] [min-height:0]`,
  loadingShell:
    "vui-routes-configroute loadingShell [grid-column:1/-1] [display:grid] [grid-template-columns:minmax(240px,var(--sidebar-width,306px))_minmax(0,1fr)] [gap:6px] [min-height:0] [height:100%] max-[1120px]:[grid-template-columns:1fr]",
  loadingSpecGrid:
    "vui-routes-configroute loadingSpecGrid [&_span]:[display:block] [&_span]:[border-radius:6px] [&_span]:[background:var(--vui-gradient-route-soft)] [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [gap:7px] [&_span]:[min-height:76px]",
  loadingSurface:
    `vui-routes-configroute loadingSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:hidden] [place-items:start]`,
  matrixGrid:
    "vui-routes-configroute matrixGrid [display:grid] [gap:8px] [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[1400px]:[grid-template-columns:repeat(auto-fit,minmax(220px,1fr))] max-[720px]:[grid-template-columns:1fr]",
  notice:
    "vui-routes-configroute notice relative z-10 m-0 min-w-0 shrink-0 [color:var(--fg-secondary)] [line-height:1.38] [overflow-wrap:anywhere] [padding:7px_9px] [border-radius:8px] [border:1px_solid_var(--border-hairline)] [background:var(--vui-surface-row)]",
  noticeError:
    "vui-routes-configroute noticeError [color:var(--state-error)] [background:color-mix(in_srgb,var(--state-error)_14%,transparent)] [border-color:color-mix(in_srgb,var(--state-error)_24%,transparent)]",
  noticeSuccess:
    "vui-routes-configroute noticeSuccess [color:var(--state-success)] [background:color-mix(in_srgb,var(--accent-cool)_12%,transparent)] [border-color:color-mix(in_srgb,var(--accent-cool)_24%,transparent)]",
  page:
    "vui-routes-configroute page [--control-height:36px] [--vui-control-height-sm:36px] [--control-radius:var(--radius-control)] [--config-row-gap:10px] [--config-section-x:12px] [--config-section-y:10px] flex h-full min-h-0 min-w-0 flex-col overflow-hidden isolation-isolate bg-vui-surface-workspace max-[720px]:h-auto max-[720px]:overflow-visible",
  // Wave 4B: shared PaneResizeHandle visual; only breakpoint hide stays local.
  /** Split owns nav/main widths via WORKBENCH_LAYOUT_IDS.configSettings. */
  settingsSplit:
    "vui-routes-configroute settingsSplit h-full min-h-0 min-w-0 flex-1 max-[720px]:!flex-col max-[720px]:overflow-visible",
  primaryButton:
    `vui-routes-configroute primaryButton [display:inline-flex] [align-items:center] [justify-content:center] [gap:7px] [min-height:40px] [padding:0_16px] [border-radius:var(--control-radius)] [font:inherit] [font-size:var(--vui-font-sm)] [font-weight:700] [line-height:1] [white-space:nowrap] [transition:border-color_140ms_ease,background-color_140ms_ease,color_140ms_ease] ${primaryControl} [box-shadow:none] hover:[cursor:pointer] hover:[border-color:color-mix(in_srgb,var(--accent-warm)_40%,transparent)] hover:[background:color-mix(in_srgb,var(--accent-warm)_20%,var(--vui-control-muted))] disabled:[cursor:not-allowed] disabled:[opacity:0.56]`,
  profileTableWrap:
    "vui-routes-configroute profileTableWrap [width:100%] [min-width:0] [overflow-x:auto] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-row)] [scrollbar-gutter:stable]",
  returnButton:
    "vui-routes-configroute returnButton [display:inline-flex] [align-items:center] [justify-self:start] [gap:5px] [min-height:27px] [max-width:100%] [padding:0_8px] [border:1px_solid_var(--border-hairline)] [border-radius:var(--control-radius)] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [font-weight:700] [text-decoration:none] hover:[border-color:var(--border-strong)] hover:[color:var(--fg-primary)] hover:[background:var(--vui-surface-row-hover)] [&_svg]:[transform:rotate(180deg)]",
  sectionHeader:
    `vui-routes-configroute sectionHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [min-height:40px] [padding:7px_var(--config-section-x)] ${sectionHeaderSurface}`,
  sectionHeaderActions:
    "vui-routes-configroute sectionHeaderActions [display:flex] [align-items:center] [justify-content:end] [gap:6px] [flex-wrap:wrap]",
  sectionHeaderMain:
    "vui-routes-configroute sectionHeaderMain [display:grid] [gap:3px] [min-width:0]",
  sectionSurface:
    `vui-routes-configroute sectionSurface ${panelSurface} [display:grid] [gap:0] [padding:0] [scroll-margin-top:84px] [overflow:visible] [&>_.sectionText]:[padding:6px_var(--config-section-x)_0] [&>_.sectionText]:[max-width:980px] [&>_.sectionText]:[font-size:var(--vui-font-xs)] [&>_:where(_.hashGrid,.matrixGrid,.healthSummaryGrid,.logHelperGrid,.toggleGrid,.healthWorkbenchGrid,.profileTableWrap,.formSurface,.actionsRow,.rawConfigPanel,.editorWrap,.agentRunPanel_)]:[margin:var(--config-section-y)_var(--config-section-x)_var(--config-section-x)] [&>_.sectionText_+_:where(_.hashGrid,.matrixGrid,.healthSummaryGrid,.logHelperGrid,.toggleGrid,.healthWorkbenchGrid,.profileTableWrap,.formSurface,.actionsRow,.rawConfigPanel,.editorWrap_)]:[margin-top:6px]`,
  sectionText:
    "vui-routes-configroute sectionText [margin:0] [color:var(--fg-secondary)] [line-height:1.38]",
  sectionTitle:
    "vui-routes-configroute sectionTitle [margin:1px_0_0] [color:var(--fg-primary)] [font-size:0.92rem] [line-height:1.15]",
  sectionToolbarGroup:
    "vui-routes-configroute sectionToolbarGroup [display:inline-flex] [align-items:center] [gap:4px] [padding:3px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_86%,transparent)] [border-radius:999px] [background:var(--vui-surface-toolbar)] [flex-wrap:wrap] [justify-content:end]",
  sidebar:
    `vui-routes-configroute sidebar ${readablePanelSurface} [position:sticky] [top:0] [display:flex] [flex-direction:column] [gap:var(--config-row-gap)] [padding:8px] [min-height:360px] [max-height:calc(100dvh_-_28px)] [overflow-x:hidden] [overflow-y:auto] [overscroll-behavior:contain] [scrollbar-gutter:stable] max-[1120px]:[position:static] max-[1120px]:[min-height:0] max-[1120px]:[height:auto!important] max-[1120px]:[max-height:none] max-[1120px]:[overflow:visible]`,
  sidebarMetrics:
    "vui-routes-configroute sidebarMetrics [display:grid] [grid-template-columns:repeat(2,minmax(0,1fr))] [gap:6px] max-[720px]:[grid-template-columns:1fr]",
  sidebarMetaStrip:
    "vui-routes-configroute sidebarMetaStrip [display:flex] [align-items:center] [gap:5px] [flex-wrap:wrap] [padding-top:1px]",
  sidebarStatusCompact:
    `vui-routes-configroute sidebarStatusCompact ${readableRowSurface} [display:grid] [gap:5px] [padding:8px]`,
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
  toggleField:
    "vui-routes-configroute toggleField [display:grid] [gap:4px] [&_span]:[overflow-wrap:anywhere] [&>_span]:[color:var(--fg-tertiary)] [&>_span]:[font-size:var(--vui-font-xs)] [display:flex] [align-items:center] [min-height:var(--control-height)] [padding:6px_8px] [border:1px_solid_var(--border-hairline)] [border-radius:7px] [background:var(--vui-surface-row)] [color:var(--fg-secondary)] [&_input]:[width:16px] [&_input]:[height:16px]",
  toolbarButton:
    "vui-routes-configroute toolbarButton [border-radius:999px]",
  treeBody:
    "vui-routes-configroute treeBody [display:grid] [gap:8px]",
  treeFieldCard:
    "vui-routes-configroute treeFieldCard grid min-w-0 gap-2 border-b border-vui-border-subtle py-4",
  treeFieldCardEdit:
    "vui-routes-configroute treeFieldCardEdit content-start gap-3 py-4 [&_.field]:grid-cols-[16rem_minmax(0,1fr)] [&_.field]:gap-x-8",
  treeFieldCardView:
    "vui-routes-configroute treeFieldCardView grid-cols-[16rem_minmax(0,1fr)] items-start gap-x-8 [&_.treeFieldHead]:col-start-1 [&_.treeFieldHead]:row-start-1 [&_.treeFieldHead]:justify-start [&_.treeFieldValue]:col-start-2 [&_.treeFieldValue]:row-start-1 [&_.treeFieldValue]:justify-self-start [&_.treeFieldValue]:max-w-full [&_.treeHint]:col-start-1 [&_.treeHint]:col-span-2 [&_.treeHint]:row-start-2",
  treeFieldHead:
    "vui-routes-configroute treeFieldHead [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [align-items:center]",
  treeFieldLabel:
    "vui-routes-configroute treeFieldLabel text-sm font-medium text-vui-fg-primary",
  treeFieldValue:
    "vui-routes-configroute treeFieldValue text-sm leading-relaxed text-vui-fg-secondary break-words",
  treeGrid:
    "vui-routes-configroute treeGrid grid min-w-0 grid-cols-1 gap-0",
  treeHint:
    "vui-routes-configroute treeHint [margin:0] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [line-height:1.35]",
  treeNestedBlock:
    "vui-routes-configroute treeNestedBlock grid min-w-0 gap-3 border-t border-vui-border-subtle pt-3",
  treeNestedHeader:
    "vui-routes-configroute treeNestedHeader [display:flex] [align-items:start] [justify-content:space-between] [gap:8px] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:600]",
  treeObjectBlock:
    "vui-routes-configroute treeObjectBlock grid min-w-0 gap-3 border-t border-vui-border-subtle pt-3",
  treeObjectCell:
    "vui-routes-configroute treeObjectCell [min-width:0] [&_.treeObjectBlock]:[min-height:42px] [&_.treeNestedBlock]:[min-height:42px] [&_.treeToggle]:[min-height:34px] [&_.treeToggle_.treeHint]:[display:none]",
  treeStack:
    "vui-routes-configroute treeStack [display:grid] [gap:6px]",
  treeToggle:
    "vui-routes-configroute treeToggle !flex !w-full !justify-between !items-center gap-3 !border-0 !bg-transparent !px-0 !py-2 text-left",
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
    "vui-routes-configroute userProfileAvatarFields grid min-w-0 grid-cols-1 gap-0",
  userProfileAvatarGroup:
    "vui-routes-configroute userProfileAvatarGroup [min-width:0] [display:grid] [gap:6px]",
  userProfileAvatarHeader:
    "vui-routes-configroute userProfileAvatarHeader [display:flex] [align-items:center] [justify-content:space-between] [gap:12px] [min-width:0] [padding:0_2px] [&_strong]:[flex:0_0_auto] [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_strong]:[font-weight:700] [&_strong]:[line-height:1.2] [&_span]:[min-width:0] [&_span]:[overflow:hidden] [&_span]:[color:var(--fg-tertiary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[line-height:1.25] [&_span]:[text-overflow:ellipsis] [&_span]:[white-space:nowrap] max-[720px]:[align-items:start] max-[720px]:[flex-direction:column] max-[720px]:[gap:3px] max-[720px]:[&_span]:[white-space:normal]",
  userProfileIdentityFields:
    "vui-routes-configroute userProfileIdentityFields [display:grid] [gap:6px] [min-width:0] [grid-template-columns:minmax(0,1fr)]",
  userProfileLayout:
    "vui-routes-configroute userProfileLayout grid min-w-0 max-w-[72rem] gap-5 p-4",
  userProfilePrimaryGrid:
    "vui-routes-configroute userProfilePrimaryGrid grid min-w-0 max-w-[72rem] grid-cols-1 gap-5",
  userProfileAdvancedFields:
    "vui-routes-configroute userProfileAdvancedFields [display:grid] [gap:6px] [min-width:0] [grid-template-columns:minmax(0,1fr)]",
} as const;

export default styles;
