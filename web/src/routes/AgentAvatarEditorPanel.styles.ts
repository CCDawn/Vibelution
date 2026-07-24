import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  contextualHintRow: "inline-flex [align-items:center] [gap:6px]",
  avatarEditorAnchor: "[position:relative] [flex:0_0_auto]",
  detailAvatarButton: "grid w-[46px] h-[46px] [place-items:center] [width:46px] [height:46px] [padding:0] [border:0] [border-radius:50%] [background:transparent] [color:inherit] [cursor:pointer] focus-visible:[outline:none]",
  detailAvatar: "grid [place-items:center] [flex:0_0_auto] [border-radius:50%] [color:var(--fg-primary)] [background:color-mix(in_srgb,_var(--accent-cool)_12%,_transparent)] [font-family:var(--font-display)] [font-weight:800] [overflow:hidden] [width:46px] [height:46px] [font-size:var(--vui-font-xs)] [outline:1px_solid_color-mix(in_srgb,_var(--accent-cool)_24%,_transparent)]",
  agentAvatarImage: "block [width:100%] [height:100%] [border-radius:inherit] [object-fit:cover]",
  avatarEditorPanel: `[position:absolute] [top:52px] [left:0] [z-index:5] grid [gap:9px] [width:min(320px,_82vw)] [padding:10px] ${vuiFlatPanelClass} [&_p]:[margin:0] [&_p]:[color:var(--fg-secondary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:[line-height:1.4]`,
  avatarEditorHeader: "flex [align-items:center] [justify-content:space-between] [gap:8px] min-w-0 [&_strong]:block [&_strong]:[color:var(--fg-primary)] [&_strong]:[font-size:0.9rem]",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  iconButton: `grid w-[26px] h-[26px] [place-items:center] [width:26px] [height:26px] ${vuiOpaqueRowClass} [color:var(--fg-secondary)] [font:inherit] [font-size:1rem] [cursor:pointer]`,
  avatarEditorActions: "flex [flex-wrap:wrap] [gap:7px] min-w-0 [&_[data-vui=\\\"button\\\"]]:[white-space:nowrap]",
  avatarLibraryHeader: "flex [align-items:center] [justify-content:space-between] [gap:8px] min-w-0 [&_span]:[color:var(--fg-primary)] [&_span]:[font-size:var(--vui-font-xs)] [&_span]:[font-weight:800] [&_small]:[color:var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  avatarOptionGrid: "grid [grid-template-columns:repeat(auto-fill,_minmax(42px,_1fr))] [gap:7px] [max-height:178px] [overflow:auto] [padding-right:2px]",
  avatarOption: "grid w-full [place-items:center] [aspect-ratio:1] min-w-0 [padding:2px] [border:1px_solid_color-mix(in_srgb,_var(--vui-border-subtle)_76%,_transparent)] [border-radius:50%] !bg-[var(--vui-surface-row)] [cursor:pointer] hover:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)] hover:[outline:none] focus-visible:[border-color:color-mix(in_srgb,_var(--accent-cool)_48%,_transparent)] focus-visible:[outline:none] [&_img]:block [&_img]:[width:100%] [&_img]:[height:100%] [&_img]:[border-radius:inherit] [&_img]:[object-fit:cover]",
  avatarOptionSelected: "[border-color:color-mix(in_srgb,_var(--accent-warm)_58%,_transparent)] [box-shadow:none]",
  contextLine: "[margin:0] [color:var(--fg-secondary)] [font-size:var(--vui-font-xs)] [line-height:1.4]",
} as const;

export default styles;
