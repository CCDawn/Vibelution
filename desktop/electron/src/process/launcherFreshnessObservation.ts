export function createLauncherFreshnessObservation<T>(
  identity: () => string,
  load: () => Promise<T>,
): () => Promise<T> {
  let pending: { identity: string; result: Promise<T> } | undefined;
  return async () => {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const observation = pending ?? { identity: identity(), result: Promise.resolve().then(load) };
      pending = observation;
      try {
        const value = await observation.result;
        if (observation.identity === identity()) return value;
      } catch (error) {
        if (observation.identity === identity()) throw error;
      } finally {
        if (pending === observation) pending = undefined;
      }
    }
    throw new Error("Launcher version changed during inspection. Check again.");
  };
}
