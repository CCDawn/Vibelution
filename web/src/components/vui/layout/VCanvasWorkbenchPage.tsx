import {
  type ComponentPropsWithoutRef,
  type Ref,
  type RefObject,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { cn } from "../lib/cn";
import { VButton } from "../primitives/VButton";
import { VDialog } from "../primitives/VDialog";
import { VRouteHeader } from "./VRouteHeader";
import { VSplitWorkspace, type VSplitWorkspaceResizeConfig } from "./VSplitWorkspace";
import { VWorkbenchPage } from "./VWorkbenchPage";
import {
  VUI_CANVAS_SURFACE_CLASS,
  VUI_PAGE_BODY_FILL_CLASS,
  VUI_PAGE_TOOLBAR_STRIP_CLASS,
  VUI_RAIL_SURFACE_CLASS,
  VUI_WORKBENCH_SURFACE_CLASS,
} from "./pageRecipeClasses";

export type VCanvasWorkbenchDrawerConfig = {
  /** Accessible heading for the drawer and its trigger. */
  label: string;
  /** Controlled open state. Omit to use defaultOpen and internal state. */
  open?: boolean;
  /** Initial open state for the narrow/compact overlay. Defaults to false. */
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

export type VCanvasWorkbenchResponsiveConfig = {
  /** Opt-in switch. Existing canvas pages keep their fixed columns by default. */
  enabled?: boolean;
  rail?: VCanvasWorkbenchDrawerConfig;
  inspector?: VCanvasWorkbenchDrawerConfig;
};

export type VCanvasWorkbenchResponsiveMode = "wide" | "compact" | "narrow";

export type VCanvasWorkbenchPageProps = Omit<ComponentPropsWithoutRef<"section">, "children"> & {
  ariaLabel?: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  hideHeader?: boolean;
  headerClassName?: string;
  toolbar?: ReactNode;
  toolbarClassName?: string;
  /** Optional left rail (team list, layer list). */
  rail?: ReactNode;
  /** Center canvas / graph host. */
  canvas: ReactNode;
  /** Right inspector / binding panel. */
  inspector?: ReactNode;
  layoutId?: string;
  resize?: Omit<VSplitWorkspaceResizeConfig, "layoutId">;
  domainRecipe?: string;
  shellTestId?: string;
  shellMode?: string;
  railClassName?: string;
  canvasClassName?: string;
  inspectorClassName?: string;
  workspaceClassName?: string;
  /**
   * Opt-in responsive behavior: >=1280 keeps three columns, 900-1279 keeps
   * the rail and turns the Inspector into a drawer, and <900 turns both into
   * independently toggled drawers. The API is disabled when omitted.
   */
  responsive?: VCanvasWorkbenchResponsiveConfig;
  className?: string;
};

const RESPONSIVE_CONTROLS_CLASS =
  "relative z-30 flex min-w-0 shrink-0 flex-wrap items-center gap-1.5 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-2 py-1.5 min-[1280px]:hidden";

function viewportMode(): VCanvasWorkbenchResponsiveMode {
  if (typeof window === "undefined") return "wide";
  return window.innerWidth >= 1280
    ? "wide"
    : window.innerWidth >= 900
      ? "compact"
      : "narrow";
}

function useViewportMode(enabled: boolean): VCanvasWorkbenchResponsiveMode {
  const [mode, setMode] = useState<VCanvasWorkbenchResponsiveMode>(() =>
    enabled ? viewportMode() : "wide",
  );

  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      setMode("wide");
      return undefined;
    }
    const update = () => setMode(viewportMode());
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [enabled]);

  return enabled ? mode : "wide";
}

function useControllableOpen(config: VCanvasWorkbenchDrawerConfig | undefined) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(() =>
    Boolean(config?.defaultOpen),
  );
  const controlled = config?.open !== undefined;
  const open = controlled ? Boolean(config?.open) : uncontrolledOpen;
  const setOpen = useCallback(
    (next: boolean) => {
      if (!controlled) setUncontrolledOpen(next);
      config?.onOpenChange?.(next);
    },
    [config?.onOpenChange, controlled],
  );
  return [open, setOpen] as const;
}

function CanvasWorkbenchDrawer({
  side,
  id,
  title,
  open,
  onClose,
  returnFocusRef,
  children,
}: {
  side: "left" | "right";
  id: string;
  title: string;
  open: boolean;
  onClose: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  const shouldRestoreFocusRef = useRef(false);
  useEffect(() => {
    if (open || !shouldRestoreFocusRef.current) return;
    shouldRestoreFocusRef.current = false;
    const trigger =
      returnFocusRef?.current?.isConnected
        ? returnFocusRef.current
        : typeof document === "undefined"
          ? null
          : Array.from(
              document.querySelectorAll<HTMLButtonElement>(
                '[data-vui="canvas-workbench-drawer-toggle"]',
              ),
            ).find((button) => button.getAttribute("aria-controls") === id) ?? null;
    trigger?.focus();
  }, [id, open, returnFocusRef]);

  const panelClassName = cn(
    "!top-[var(--shell-topbar-height,0px)] !bottom-0 !h-auto !max-h-none !w-[min(88vw,380px)] !translate-x-0 !translate-y-0 rounded-none border-y-0 shadow-[var(--vui-shadow-panel)]",
    side === "left"
      ? "!left-0 !right-auto !translate-x-0 border-l-0"
      : "!left-auto !right-0 !translate-x-0 border-r-0",
  );

  return (
    <VDialog
      contentClassName={panelClassName}
      onCloseAutoFocus={(event) => {
        event.preventDefault();
      }}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          shouldRestoreFocusRef.current = true;
          onClose();
        }
      }}
      open={open}
      size="md"
      title={title}
    >
      <div
        data-vui-region="canvas-workbench-drawer"
        id={id}
        className="flex min-h-0 min-w-0 flex-1 flex-col"
      >
        {children}
      </div>
    </VDialog>
  );
}

function ResponsiveDrawerToggle({
  label,
  open,
  controlsId,
  buttonRef,
  onToggle,
}: {
  label: string;
  open: boolean;
  controlsId: string;
  buttonRef: Ref<HTMLButtonElement>;
  onToggle: () => void;
}) {
  return (
    <VButton
      aria-controls={controlsId}
      aria-expanded={open}
      data-vui="canvas-workbench-drawer-toggle"
      ref={buttonRef}
      type="button"
      variant="secondary"
      onPress={onToggle}
    >
      {open ? `关闭${label}` : `打开${label}`}
    </VButton>
  );
}

/**
 * Page recipe: full-height canvas workbench with optional rail + inspector.
 * Prefer for org graphs, flow canvases, and memory graphs.
 */
export function VCanvasWorkbenchPage({
  ariaLabel,
  eyebrow,
  title,
  meta,
  actions,
  hideHeader = false,
  headerClassName,
  toolbar,
  toolbarClassName,
  rail,
  canvas,
  inspector,
  layoutId,
  resize,
  domainRecipe,
  shellTestId,
  shellMode,
  railClassName,
  canvasClassName,
  inspectorClassName,
  workspaceClassName,
  responsive,
  className,
  ...props
}: VCanvasWorkbenchPageProps) {
  const resizeConfig = layoutId
    ? { layoutId, enabled: true as const, ...resize }
    : false;
  const responsiveEnabled = Boolean(responsive?.enabled);
  const mode = useViewportMode(responsiveEnabled);
  const [railOpen, setRailOpen] = useControllableOpen(responsive?.rail);
  const [inspectorOpen, setInspectorOpen] = useControllableOpen(
    responsive?.inspector,
  );
  const railToggleRef = useRef<HTMLButtonElement>(null);
  const inspectorToggleRef = useRef<HTMLButtonElement>(null);
  const railLabel = responsive?.rail?.label || "左侧栏";
  const inspectorLabel = responsive?.inspector?.label || "检查器";
  const showRailDrawer =
    responsiveEnabled && mode === "narrow" && Boolean(rail);
  const showInspectorDrawer =
    responsiveEnabled && mode !== "wide" && Boolean(inspector);
  const showRailToggle = showRailDrawer;
  const showInspectorToggle = showInspectorDrawer;
  const visibleRail = responsiveEnabled && mode === "narrow" ? undefined : rail;
  const visibleInspector =
    responsiveEnabled && mode !== "wide" ? undefined : inspector;
  const responsiveId = useId().replace(/:/g, "");
  const railDrawerId = `canvas-workbench-drawer-left-${responsiveId}`;
  const inspectorDrawerId = `canvas-workbench-drawer-right-${responsiveId}`;

  return (
    <VWorkbenchPage
      ariaLabel={ariaLabel}
      data-vui-recipe="canvas-workbench-page"
      data-vui-domain-recipe={domainRecipe}
      fill
      // hideHeader → single body child; must use stack or body collapses to content height.
      fillLayout={hideHeader ? "stack" : "header-body"}
      className={className}
      {...props}
    >
      {hideHeader ? null : (
        <VRouteHeader
          className={headerClassName}
          eyebrow={eyebrow}
          title={title}
          meta={meta}
          actions={actions}
        />
      )}
      <div data-vui="canvas-workbench-body" className={cn(VUI_PAGE_BODY_FILL_CLASS, "min-h-0 flex-1")}>
        {responsiveEnabled && (showRailToggle || showInspectorToggle) ? (
          <div
            aria-label="画布工作区面板"
            className={RESPONSIVE_CONTROLS_CLASS}
            data-vui="canvas-workbench-responsive-controls"
          >
            {showRailToggle ? (
              <ResponsiveDrawerToggle
                controlsId={railDrawerId}
                buttonRef={railToggleRef}
                label={railLabel}
                open={railOpen}
                onToggle={() => setRailOpen(!railOpen)}
              />
            ) : null}
            {showInspectorToggle ? (
              <ResponsiveDrawerToggle
                controlsId={inspectorDrawerId}
                buttonRef={inspectorToggleRef}
                label={inspectorLabel}
                open={inspectorOpen}
                onToggle={() => setInspectorOpen(!inspectorOpen)}
              />
            ) : null}
          </div>
        ) : null}
        {toolbar ? (
          <div
            data-vui="canvas-workbench-toolbar"
            className={cn(VUI_PAGE_TOOLBAR_STRIP_CLASS, "relative z-20 shrink-0 overflow-hidden", toolbarClassName)}
          >
            {toolbar}
          </div>
        ) : null}
        {/*
          Do not pair h-full with a toolbar sibling: height 100% of body overflows the
          toolbar strip and clips the canvas. flex-1 min-h-0 fills the remainder.
        */}
        <VSplitWorkspace
          className={cn("min-h-0 min-w-0 flex-1 overflow-hidden !h-auto", workspaceClassName)}
          data-testid={shellTestId}
          data-team-shell-mode={shellMode}
          data-vui-layout-id={layoutId}
          resize={resizeConfig}
          sidebar={
            visibleRail
              ? (
                <div
                  data-vui="canvas-workbench-rail"
                  className={cn(VUI_RAIL_SURFACE_CLASS, "flex h-full min-h-0 flex-col", railClassName)}
                >
                  {visibleRail}
                </div>
              )
              : undefined
          }
          main={(
            <div
              data-vui="canvas-workbench-canvas"
              className={cn(
                VUI_CANVAS_SURFACE_CLASS,
                // Match VBoardWorkbenchPage main: stretch inside split-main.
                "relative flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
                canvasClassName,
              )}
            >
              {canvas}
            </div>
          )}
          aside={
            visibleInspector
              ? (
                <div
                  data-vui="canvas-workbench-inspector"
                  className={cn(
                    VUI_WORKBENCH_SURFACE_CLASS,
                    "flex h-full min-h-0 flex-col overflow-hidden",
                    inspectorClassName,
                  )}
                >
                  {visibleInspector}
                </div>
              )
              : undefined
          }
        />
        {showRailDrawer ? (
          <CanvasWorkbenchDrawer
            id={railDrawerId}
            side="left"
            title={railLabel}
            open={railOpen}
            returnFocusRef={railToggleRef}
            onClose={() => setRailOpen(false)}
          >
            {rail}
          </CanvasWorkbenchDrawer>
        ) : null}
        {showInspectorDrawer ? (
          <CanvasWorkbenchDrawer
            id={inspectorDrawerId}
            side="right"
            title={inspectorLabel}
            open={inspectorOpen}
            returnFocusRef={inspectorToggleRef}
            onClose={() => setInspectorOpen(false)}
          >
            {inspector}
          </CanvasWorkbenchDrawer>
        ) : null}
      </div>
    </VWorkbenchPage>
  );
}
