import { applyConfigWorkspace, previewConfigDraft } from "../../api/config";
import { asRecord, clonePublicConfig, type PublicConfigShape } from "../configRouteLogic";
import { configValuesEqual } from "./configFieldEditorsModel";

export type ConfigValueChange = { path: readonly string[]; value: unknown };

function copy<T>(value: T): T {
  return value === undefined ? value : clonePublicConfig(value);
}

/** Use key segments so model IDs containing periods remain literal keys. */
function replaceValue(root: unknown, path: readonly string[], value: unknown): unknown {
  if (!path.length) return copy(value);
  const [key, ...rest] = path;
  if (Array.isArray(root)) {
    const next = root.slice();
    next[Number(key)] = replaceValue(root[Number(key)], rest, value);
    return next;
  }
  const record = asRecord(root);
  return { ...record, [key]: replaceValue(record[key], rest, value) };
}

export function applyConfigValueChanges(config: PublicConfigShape, changes: readonly ConfigValueChange[]): PublicConfigShape {
  return changes.reduce((next, change) => replaceValue(next, change.path, change.value) as PublicConfigShape, config);
}

/** Save a bounded edit against the saved baseline, never against the working draft. */
export async function persistConfigChanges(baseConfig: PublicConfigShape, baseHash: string, changes: readonly ConfigValueChange[]) {
  if (!baseHash || !changes.length) throw new Error("Missing saved configuration baseline");
  const draftMeta = { pending_api_keys: {}, pending_cleared_api_keys: [] };
  const preview = await previewConfigDraft({ publicConfig: applyConfigValueChanges(baseConfig, changes), baseHash, draftMeta });
  return applyConfigWorkspace({ publicConfig: preview.publicConfig, baseConfig, baseHash, draftMeta });
}

function rebaseValue(base: unknown, local: unknown, saved: unknown): unknown {
  if (configValuesEqual(base, local)) return copy(saved);
  if (base && local && saved && !Array.isArray(base) && !Array.isArray(local) && !Array.isArray(saved)
    && typeof base === "object" && typeof local === "object" && typeof saved === "object") {
    const previous = asRecord(base);
    const draft = asRecord(local);
    const current = asRecord(saved);
    const keys = new Set([...Object.keys(previous), ...Object.keys(draft), ...Object.keys(current)]);
    return Object.fromEntries([...keys].flatMap((key) => {
      if (!Object.hasOwn(draft, key)) {
        return Object.hasOwn(previous, key) || !Object.hasOwn(current, key) ? [] : [[key, copy(current[key])]];
      }
      if (configValuesEqual(previous[key], draft[key]) && !Object.hasOwn(current, key)) return [];
      return [[key, rebaseValue(previous[key], draft[key], current[key])]];
    }));
  }
  // Arrays are the same atomic edit unit used by the server's three-way merge.
  return copy(local);
}

/** Keep unsaved edits while adopting the persisted operation and external changes. */
export function rebaseConfigDraft(base: PublicConfigShape, local: PublicConfigShape, saved: PublicConfigShape,
  savedPaths: readonly (readonly string[])[] = []): PublicConfigShape {
  const rebased = rebaseValue(base, local, saved) as PublicConfigShape;
  return applyConfigValueChanges(rebased, savedPaths.map((path) => ({
    path,
    value: path.reduce<unknown>((node, key) => Array.isArray(node) ? node[Number(key)] : asRecord(node)[key], saved),
  })));
}
