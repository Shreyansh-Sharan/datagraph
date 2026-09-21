import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Config, DatagraphApi, Me, Role } from "@/api";
import { ROLE_RANK } from "@/api";

interface AppState {
  api: DatagraphApi;
  config: Config;
  me: Me;
  rank: number;
  can: (role: Role) => boolean;
  toast: string | null;
  say: (msg: string) => void;
  setRole: (role: Role) => void;      // identity switch (header mode / demo)
  refreshKey: number;
  refresh: () => void;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ api, children }: { api: DatagraphApi; children: ReactNode }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    let alive = true;
    Promise.all([api.config(), api.me()]).then(([c, m]) => { if (alive) { setConfig(c); setMe(m); } }).catch(e => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => { alive = false; };
  }, [api]);

  const say = useCallback((msg: string) => { setToast(msg); clearTimeout(timer.current); timer.current = setTimeout(() => setToast(null), 3500); }, []);
  const setRole = useCallback((role: Role) => setMe(m => (m ? { ...m, role } : m)), []);
  const refresh = useCallback(() => setRefreshKey(k => k + 1), []);

  const value = useMemo<AppState | null>(() => (config && me ? { api, config, me, rank: ROLE_RANK[me.role], can: r => ROLE_RANK[me.role] >= ROLE_RANK[r], toast, say, setRole, refreshKey, refresh } : null), [api, config, me, toast, say, setRole, refreshKey, refresh]);

  if (error) return <div className="empty-state"><h2 style={{ fontSize: 18, fontWeight: 800, marginBottom: 6 }}>Cannot reach the API</h2><p className="muted">{error}</p></div>;
  if (!value) return <div className="dg-app" aria-busy="true"><div className="topbar"><span className="brand"><span className="star">★</span>datagraph</span></div></div>;
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside AppProvider");
  return v;
}

/** Load data with the standard loading / error triple; re-runs when deps or the global refresh key change. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]): { data: T | null; error: string | null; loading: boolean; reload: () => void } {
  const { refreshKey } = useApp();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true; setLoading(true); setError(null);
    fn().then(d => { if (alive) { setData(d); setLoading(false); } }).catch(e => { if (alive) { setError(e instanceof Error ? e.message : String(e)); setLoading(false); } });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refreshKey, tick]);
  return { data, error, loading, reload: () => setTick(t => t + 1) };
}
