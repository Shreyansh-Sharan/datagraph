import { MockApi } from "./mock";
import { RestApi } from "./rest";
import type { DatagraphApi, Role, SourceKind } from "./types";

export * from "./types";
export { MockApi, RestApi };

/** The adapter this build talks to. The mock has to be asked for by name: a forgotten setting
 *  must reach the real API and fail visibly, never serve design data as though it were real.
 *  The mock honours VITE_SOURCE_KIND and VITE_ROLE. */
export function createApi(env: Record<string, string | undefined> = import.meta.env): DatagraphApi {
  if ((env.VITE_API_MODE ?? "").trim().toLowerCase() === "mock") {
    return new MockApi({ sourceKind: (env.VITE_SOURCE_KIND as SourceKind) || "databricks", role: (env.VITE_ROLE as Role) || "admin", catalogDenied: env.VITE_CATALOG_DENIED === "true" });
  }
  return new RestApi({ base: env.VITE_API_BASE ?? "/api", actor: env.VITE_ACTOR });
}

/** True when this build serves design data rather than a backend. Screens use it to say so. */
export function isMockBuild(env: Record<string, string | undefined> = import.meta.env): boolean {
  return (env.VITE_API_MODE ?? "").trim().toLowerCase() === "mock";
}
