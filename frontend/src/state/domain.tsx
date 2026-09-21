import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { DomainSummary, VersionInfo } from "@/api";
import { useApp, useLoad } from "./app";
import { EmptyState, Skeleton } from "@/components/ui";

export type Screen = "overview" | "versions" | "ask" | "settings" | "metadata" | "table" | "ontology" | "mapping" | "rules" | "quality" | "build" | "explore" | "triples" | "analytics";
export const DESIGN_SCREENS: Screen[] = ["metadata", "ontology", "mapping", "rules", "quality", "build", "explore", "triples", "analytics"];

interface DomainState {
  domain: DomainSummary;
  versions: VersionInfo[];
  version: VersionInfo | null;      // selected (null when the domain has none)
  editable: boolean;                // draft + builder rank
  setVersion: (n: number) => void;
  reload: () => void;
  patch: (d: DomainSummary) => void;
}

const Ctx = createContext<DomainState | null>(null);

/** Navigation inside a domain: keeps the selected version, merges extra search params. */
export function useGo() {
  const navigate = useNavigate();
  const { name } = useParams();
  const [sp] = useSearchParams();
  return useCallback((screen: Screen | string, params: Record<string, string | number | undefined> = {}, domain = name) => {
    const q = new URLSearchParams();
    const v = params.v ?? sp.get("v");
    if (v !== undefined && v !== null && params.v !== "") q.set("v", String(v));
    for (const [k, val] of Object.entries(params)) if (k !== "v" && val !== undefined && val !== "") q.set(k, String(val));
    const qs = q.toString();
    navigate(`/d/${encodeURIComponent(domain ?? "")}/${screen}${qs ? `?${qs}` : ""}`);
  }, [navigate, name, sp]);
}

export function useParam(key: string, fallback = ""): [string, (v: string) => void] {
  const [sp, setSp] = useSearchParams();
  // Functional update: two setters called in the same handler (schema + table) must not overwrite each other.
  const set = useCallback((v: string) => { setSp(prev => { const n = new URLSearchParams(prev); if (v) n.set(key, v); else n.delete(key); return n; }, { replace: true }); }, [setSp, key]);
  return [sp.get(key) ?? fallback, set];
}

/** Several query params in one navigation. Two useParam setters in one handler would each start from
 *  the render-time params and the second would discard the first; this writes them together. */
export function useSetParams(): (patch: Record<string, string | number | null | undefined>) => void {
  const [sp, setSp] = useSearchParams();
  return useCallback(patch => { const n = new URLSearchParams(sp); for (const [k, v] of Object.entries(patch)) { if (v === undefined || v === null || v === "") n.delete(k); else n.set(k, String(v)); } setSp(n, { replace: true }); }, [sp, setSp]);
}

export function DomainProvider({ children }: { children: ReactNode }) {
  const { api, rank } = useApp();
  const { name = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const { data, error, loading, reload } = useLoad(() => api.domain(name), [name]);
  const [local, setLocal] = useLocalDomain(data);

  const domain = local ?? data;
  const value = useMemo<DomainState | null>(() => {
    if (!domain) return null;
    const versions = domain.versions;
    const wanted = Number(sp.get("v"));
    const version = versions.find(v => v.version === wanted) ?? versions[0] ?? null;
    return {
      domain, versions, version,
      editable: !!version && version.status === "draft" && rank >= 1,
      setVersion: n => { const q = new URLSearchParams(sp); q.set("v", String(n)); setSp(q); },
      reload, patch: d => setLocal(d),
    };
  }, [domain, sp, setSp, rank, reload, setLocal]);

  if (error) return <EmptyState title="Domain not found" text={error} />;
  if (loading || !value) return <div className="dg-body"><aside className="sidenav"><Skeleton h={44} /><Skeleton h={20} style={{ marginTop: 16 }} /><Skeleton h={20} /><Skeleton h={20} /></aside><main className="dg-main"><Skeleton h={28} w={220} /><Skeleton h={14} w={420} style={{ marginTop: 10 }} /></main></div>;
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// Local mirror so lifecycle actions can update the shell without a round trip.
import { useEffect, useState } from "react";
function useLocalDomain(data: DomainSummary | null): [DomainSummary | null, (d: DomainSummary | null) => void] {
  const [local, setLocal] = useState<DomainSummary | null>(null);
  useEffect(() => { setLocal(null); }, [data]);
  return [local, setLocal];
}

export function useDomain(): DomainState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useDomain outside DomainProvider");
  return v;
}
