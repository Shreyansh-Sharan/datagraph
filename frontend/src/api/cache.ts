// A per-session memo for reads that should not run again on every visit: the Metadata screen's
// schemas and tables. Entries belong to the api instance that made them, live for a while, and are
// dropped by the actions that change what they hold.
const stores = new WeakMap<object, Map<string, { at: number; value: Promise<unknown> }>>();
const TTL = 5 * 60_000;

export function memo<T>(owner: object, key: string, fn: () => Promise<T>, ttl = TTL): Promise<T> {
  let store = stores.get(owner);
  if (!store) { store = new Map(); stores.set(owner, store); }
  const hit = store.get(key);
  if (hit && Date.now() - hit.at < ttl) return hit.value as Promise<T>;
  const value = fn();
  store.set(key, { at: Date.now(), value });
  value.catch(() => store!.delete(key));   // a failure is not worth remembering
  return value;
}

/** Drop every entry of the owner whose key starts with the prefix (a domain, a version). */
export function forget(owner: object, prefix: string): void {
  const store = stores.get(owner);
  if (!store) return;
  for (const k of [...store.keys()]) if (k.startsWith(prefix)) store.delete(k);
}
