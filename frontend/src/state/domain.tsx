import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { DomainSummary, VersionInfo } from "@/api";
import { useApp, useLoad } from "./app";

export type Screen = "overview" | "versions" | "ask" | "settings" | "metadata" | "table" | "ontology" | "mapping" | "rules" | "quality" | "build" | "explore" | "triples" | "analytics";
export const DESIGN_SCREENS: Screen[] = ["metadata", "ontology", "mapping", "rules", "quality", "build", "explore", "triples", "analytics"];

/** The five sections of a domain (the rail) and the tabs each one shows across the top. */
export type Section = "ask" | "overview" | "design" | "graph" | "versions";
export interface SectionTab { id: string; label: string; screen: Screen; tab?: string }
export const SECTIONS: { id: Section; label: string; icon: string; home: Screen; tabs: SectionTab[] }[] = [
  { id: "ask", label: "Ask", icon: "ask", home: "ask", tabs: [] },
  { id: "overview", label: "Overview", icon: "overview", home: "overview", tabs: [
    { id: "summary", label: "Summary", screen: "overview" }, { id: "connections", label: "Connections", screen: "overview", tab: "connections" },
    { id: "domain", label: "Domain", screen: "overview", tab: "domain" },
    { id: "mcp", label: "MCP policy", screen: "overview", tab: "mcp" }] },
  { id: "design", label: "Design", icon: "design", home: "metadata", tabs: [
    { id: "metadata", label: "Metadata", screen: "metadata" }, { id: "ontology", label: "Ontology", screen: "ontology" }, { id: "mapping", label: "Mapping", screen: "mapping" },
    { id: "rules", label: "Rules", screen: "rules" }, { id: "quality", label: "Data quality", screen: "quality" }] },
  { id: "graph", label: "Graph", icon: "graph", home: "build", tabs: [
    { id: "build", label: "Build", screen: "build" }, { id: "explore", label: "Explore", screen: "explore" }, { id: "triples", label: "Triples", screen: "triples" }, { id: "analytics", label: "Analytics", screen: "analytics" }] },
  { id: "versions", label: "Versions", icon: "versions", home: "versions", tabs: [] },
];
export function sectionOf(screen: string): Section {
  if (screen === "ask") return "ask";
  if (screen === "versions") return "versions";
  if (["metadata", "table", "ontology", "mapping", "rules", "quality"].includes(screen)) return "design";
  if (["build", "explore", "triples", "analytics"].includes(screen)) return "graph";
  return "overview";
}

interface DomainState {
  domain: DomainSummary;
  versions: VersionInfo[];
  version: VersionInfo | null;      // selected (null when the domain has none)
  editable: boolean;                // draft + builder rank
  sourceKind: string;               // the domain's own source: "postgres" | "databricks" (the deployment default until its facts arrive)
  setVersion: (n: number) => void;
  reload: () => void;
  patch: (d: DomainSummary) => void;
}

const Ctx = createContext<DomainState | null>(null);
const LoadCtx = createContext<{ loading: boolean; error: string | null }>({ loading: false, error: null });

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
  const { api, rank, config } = useApp();
  const { name = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const { data, error, loading, reload } = useLoad(() => api.domain(name), [name]);
  const facts = useLoad(() => api.sourceFacts(name).catch(() => null), [name]);
  const sourceKind = facts.data?.kind || config.sourceKind;
  const [local, setLocal] = useLocalDomain(data);

  const domain = local ?? data;
  const value = useMemo<DomainState | null>(() => {
    if (!domain) return null;
    const versions = domain.versions;
    const wanted = Number(sp.get("v"));
    const version = versions.find(v => v.version === wanted) ?? versions[0] ?? null;
    return {
      domain, versions, version,
      editable: !!version && version.status === "draft" && rank >= 1, sourceKind,
      setVersion: n => { const q = new URLSearchParams(sp); q.set("v", String(n)); setSp(q); },
      reload, patch: d => setLocal(d),
    };
  }, [domain, sp, setSp, rank, reload, setLocal, sourceKind]);

  // Children always render: the top bar shows the domain crumb while it loads, and DomainShell shows the skeleton or the error.
  return <LoadCtx.Provider value={{ loading: !value && !error && loading, error }}><Ctx.Provider value={value}>{children}</Ctx.Provider></LoadCtx.Provider>;
}

/** The domain when it is loaded, else null (for frames rendered before or while it loads). */
export function useDomainOptional(): DomainState | null {
  return useContext(Ctx);
}

export function useDomainLoad(): { loading: boolean; error: string | null } {
  return useContext(LoadCtx);
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
