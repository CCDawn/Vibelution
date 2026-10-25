import { measureElement, type Virtualizer } from "@tanstack/react-virtual";

export function measureConversationVirtualRow<TScrollElement extends Element | Window, TItemElement extends Element>(
  element: TItemElement,
  entry: ResizeObserverEntry | undefined,
  instance: Virtualizer<TScrollElement, TItemElement>,
): number {
  // TanStack attaches its observer before requesting the initial synchronous
  // size. Let that observer deliver the border box after layout, retaining
  // the library's stable-key cache and estimate until then.
  if (!entry && typeof element.ownerDocument.defaultView?.ResizeObserver === "function") {
    const index = instance.indexFromElement(element);
    const key = instance.options.getItemKey(index);
    return instance.itemSizeCache.get(key) ?? instance.options.estimateSize(index);
  }
  return measureElement(element, entry, instance);
}
