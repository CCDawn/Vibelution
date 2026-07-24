import {
  vuiGlassPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  conversationFrame:
    "vui-routes-chatsessionworkspacepanel conversationFrame relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden",
  conversationFrameFocus:
    "vui-routes-chatsessionworkspacepanel conversationFrameFocus min-w-0 justify-self-center w-[min(calc(100%_-_48px),1480px)] max-w-full max-[980px]:w-full !w-full",
  emptyConversationSurface:
    "vui-routes-chatsessionworkspacepanel emptyConversationSurface min-h-[74px] !w-[min(360px,calc(100%_-_32px))] place-self-center !content-center !text-center",
  emptySurface:
    "vui-routes-chatsessionworkspacepanel emptySurface h-full min-h-[min(420px,calc(100dvh_-_190px))] place-self-stretch place-items-center !content-center !text-center",
  inlineNotice: `vui-routes-chatsessionworkspacepanel inlineNotice min-w-0 ${vuiGlassPanelClass} p-2`,
} as const;

export default styles;
