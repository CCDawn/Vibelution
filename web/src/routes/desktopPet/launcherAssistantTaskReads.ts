/** Native optional labels and team observations borrow the same project reader.
 * Serialize this renderer's reads without caching results: every post-action
 * refetch must still obtain its own fresh receipt. Task controls never queue here.
 */
const pendingReads = new Map<string, Promise<void>>();

export async function readLauncherAssistantTaskSource<T>(
  identity: string, signal: AbortSignal, read: () => Promise<T>,
  isCurrent: () => boolean = () => true,
): Promise<T> {
  const assertCurrent = () => {
    signal.throwIfAborted();
    if (!isCurrent()) throw new DOMException("Launcher task view changed", "AbortError");
  };
  assertCurrent();
  const previous = pendingReads.get(identity) ?? Promise.resolve();
  const result = previous.then(() => {
    assertCurrent();
    return read();
  });
  // Aborting an observer cannot cancel an IPC already executing in the host.
  // Keep its place until the actual native read settles, including on failure.
  const settled = result.then(() => {}, () => {});
  pendingReads.set(identity, settled);
  void settled.then(() => {
    if (pendingReads.get(identity) === settled) pendingReads.delete(identity);
  });
  const value = await result;
  assertCurrent();
  return value;
}
