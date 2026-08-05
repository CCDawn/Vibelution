import {
  vuiGlassPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  conversationShell:
    "vui-routes-chatsessionworkspacepanel conversationShell relative flex h-full min-h-0 min-w-0 w-full flex-col overflow-hidden",
  conversationFrame:
    "vui-routes-chatsessionworkspacepanel conversationFrame relative flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden",
  conversationBody:
    "vui-routes-chatsessionworkspacepanel conversationBody relative flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden",
  conversationKeepAlivePane:
    "vui-routes-chatsessionworkspacepanel conversationKeepAlivePane relative flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden",
  toolApprovalHost:
    "vui-routes-chatsessionworkspacepanel toolApprovalHost sticky top-0 z-[6] shrink-0 border-b border-[var(--vui-border-subtle)] !bg-vui-surface-panel px-3 py-2",
  // When status rail is closed the center track already reclaims full width.
  // Keep the reading column full-bleed inside that track (no side gutters that
  // look like a blank right panel after navigation remounts).
  conversationFrameFocus:
    "vui-routes-chatsessionworkspacepanel conversationFrameFocus min-h-0 min-w-0 w-full max-w-full",
  emptyConversationSurface:
    "vui-routes-chatsessionworkspacepanel emptyConversationSurface min-h-[74px] !w-[min(360px,calc(100%_-_32px))] place-self-center !content-center !text-center",
  emptySurface:
    "vui-routes-chatsessionworkspacepanel emptySurface h-full min-h-[min(420px,calc(100dvh_-_190px))] place-self-stretch place-items-center !content-center !text-center",
  inlineNotice: `vui-routes-chatsessionworkspacepanel inlineNotice min-w-0 ${vuiGlassPanelClass} p-2`,
} as const;

export default styles;
