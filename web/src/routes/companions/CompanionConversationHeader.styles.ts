const conversationHeader = "flex min-w-0 flex-1 items-center justify-between gap-3 py-0.5";
const conversationIdentity = "flex min-w-0 items-center gap-2.5";
const conversationAvatar = "!size-9";
const conversationIdentityCopy = "grid min-w-0 gap-0.5 [&>strong]:truncate [&>strong]:text-[0.82rem] [&>strong]:font-[780] [&>strong]:text-vui-fg-primary [&>span]:flex [&>span]:min-w-0 [&>span]:items-center [&>span]:gap-1 [&>span]:truncate [&>span]:text-[0.62rem] [&>span]:text-vui-fg-tertiary [&_i]:font-normal [&_i]:text-[var(--state-success)]";

export default {
  conversationHeader,
  conversationIdentity,
  conversationAvatar,
  conversationIdentityCopy,
} as const;
