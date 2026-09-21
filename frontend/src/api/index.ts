import { MockApi } from "./mock";
import { RestApi } from "./rest";
import type { DatagraphApi, Role, SourceKind } from "./types";

export * from "./types";
export { MockApi, RestApi };

/** Adapter chosen by environment: VITE_API_MODE=mock|rest. Mock honours VITE_SOURCE_KIND and VITE_ROLE. */
export function createApi(): DatagraphApi {
  const env = import.meta.env;
  if (env.VITE_API_MODE === "rest") return new RestApi({ base: env.VITE_API_BASE ?? "/api", actor: env.VITE_ACTOR ?? "alice" });
  return new MockApi({ sourceKind: (env.VITE_SOURCE_KIND as SourceKind) || "databricks", role: (env.VITE_ROLE as Role) || "admin", catalogDenied: env.VITE_CATALOG_DENIED === "true" });
}
