const styles={
  root:"absolute left-1/2 top-[clamp(28px,13vh,140px)] bottom-[150px] z-[1] flex w-[min(600px,calc(100%_-_56px))] -translate-x-1/2 flex-col items-center overflow-y-auto text-center [scrollbar-width:none] max-[700px]:top-8 max-[700px]:w-[calc(100%_-_32px)] [@media(max-height:700px)]:top-5",
  mark:"mb-4 grid size-14 shrink-0 place-items-center rounded-[18px] border border-vui-border-subtle bg-vui-surface-raised text-vui-fg-secondary max-[700px]:size-12 [@media(max-height:700px)]:hidden",
  eyebrow:"text-vui-micro-11 text-vui-fg-tertiary",
  heading:"mb-3 mt-3 text-2xl font-semibold leading-snug tracking-wide text-vui-fg-primary max-[700px]:text-xl",
  description:"m-0 max-w-full text-vui-micro-13 leading-relaxed text-vui-fg-tertiary",
  starters:"mt-8 grid w-full max-w-[520px] grid-cols-2 gap-3 max-[700px]:mt-6 max-[700px]:gap-2",
  starter:"!grid !h-auto !min-h-[98px] !w-full !grid-cols-[22px_minmax(0,1fr)_16px] !items-center !gap-x-2 !gap-y-2 !whitespace-normal !rounded-xl !border-vui-border-subtle !bg-vui-surface-raised !p-4 !text-left !text-vui-micro-13 max-[700px]:!grid-cols-[20px_minmax(0,1fr)] max-[700px]:!p-3 max-[700px]:[&>svg:last-of-type]:hidden",
  starterHint:"col-span-2 col-start-2 text-vui-micro-11 font-normal leading-relaxed text-vui-fg-tertiary max-[700px]:col-span-full max-[700px]:col-start-1",
} as const;
export default styles;
