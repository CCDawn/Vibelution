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
import { X } from "lucide-react";

import { cn } from "../lib/cn";
import { VButton } from "../primitives/VButton";
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
  "flex min-w-0 shrink-0 flex-wrap items-center gap-1.5 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-2 py-1.5 min-[1280px]:hidden";
const DRAWER_BACKDROP_CLASS =
  "fixed inset-0 z-[70] bg-[color-mix(in_srgb,var(--vui-surface-glass)_58%,transparent)] backdrop-blur-[1px] motion-reduce:backdrop-blur-none";
const DRAWER_PANEL_BASE_CLASS =
  "fixed inset-y-[var(--shell-topbar-height,0px)] z-[71] flex w-[min(88vw,380px)] min-h-0 flex-col overflow-hidden bg-[var(--vui-surface-rail)] shadow-[var(--vui-shadow-panel)] transition-transform duration-200 ease-out motion-reduce:transition-none";

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

function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
    ),
  );
}

let bodyScrollLockCount = 0;
let bodyOverflowBeforeScrollLock = "";

function lockBodyScroll() {
  if (typeof document === "undefined") return;
  if (bodyScrollLockCount === 0)
    bodyOverflowBeforeScrollLock = document.body.style.overflow;
  bodyScrollLockCount += 1;
  document.body.style.overflow = "hidden";
}

function unlockBodyScroll() {
  if (typeof document === "undefined" || bodyScrollLockCount === 0) return;
  bodyScrollLockCount -= 1;
  if (bodyScrollLockCount === 0)
    document.body.style.overflow = bodyOverflowBeforeScrollLock;
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
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const titleId = `canvas-workbench-drawer-title-${id}`;
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open || !drawerRef.current) return undefined;
    restoreFocusRef.current =
      returnFocusRef?.current ||
      (document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null);
    lockBodyScroll();
    closeButtonRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = focusableElements(drawerRef.current);
      if (focusable.length === 0) {
        event.preventDefault();
        drawerRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      unlockBodyScroll();
      restoreFocusRef.current?.focus();
      restoreFocusRef.current = null;
    };
  }, [open, returnFocusRef]);

  if (!open) return null;

  const panelClassName = cn(
    DRAWER_PANEL_BASE_CLASS,
    side === "left"
      ? "left-0 border-r border-[var(--vui-border-subtle)]"
      : "right-0 border-l border-[var(--vui-border-subtle)]",
  );

  return (
    <>
      <div
        aria-hidden="true"
        className={DRAWER_BACKDROP_CLASS}
        data-vui-region="canvas-workbench-drawer-backdrop"
        onMouseDown={onClose}
      />
      <div
        ref={drawerRef}
        aria-labelledby={titleId}
        aria-modal="true"
        className={panelClassName}
        data-vui-region="canvas-workbench-drawer"
        id={id}
        role="dialog"
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="flex min-w-0 shrink-0 items-center justify-between gap-2 border-b border-[var(--vui-border-subtle)] px-3 py-2">
          <h2
            className="min-w-0 truncate text-[var(--vui-font-sm)] font-semibold text-[var(--fg-primary)]"
            id={titleId}
          >
            {title}
          </h2>
          <VButton
            ref={closeButtonRef}
            aria-label={`关闭${title}`}
            data-vui="canvas-workbench-drawer-close"
            density="compact"
            isIconOnly
            title={`关闭${title}`}
            type="button"
            variant="secondary"
            icon={<X size={15} aria-hidden="true" />}
            onPress={onClose}
          />
        </header>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto [scrollbar-gutter:stable]">
          {children}
        </div>
      </div>
    </>
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
