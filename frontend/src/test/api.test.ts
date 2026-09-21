import { describe, expect, it, vi } from "vitest";
import { MockApi } from "@/api/mock";
import { RestApi } from "@/api/rest";
import { compileClassSql, tableName } from "@/api/types";
import { answer } from "@/screens/askEngine";
import * as D from "@/api/mockData";

describe("adapter-aware naming", () => {
  it("uses three-part names on Databricks and schema-prefixed names on Postgres", () => {
    expect(tableName("databricks", "rgm", "gold", "dim_customer")).toBe("rgm.gold.dim_customer");
    expect(tableName("postgres", "rgm", "gold", "dim_customer")).toBe("rgm_gold.dim_customer");
  });
  it("compiles class SQL in the dialect of the running adapter", () => {
    const dbx = compileClassSql("databricks", "http://polestar.ai/rgm/", "Customer", D.MAP.Customer, "rgm");
    expect(dbx).toContain("`rgm`.`gold`.`dim_customer`");
    expect(dbx).toContain("url_encode(CAST(`customer_id` AS STRING))");
    expect(dbx).toContain("CAST(`customer_name` AS STRING)");
    const pg = compileClassSql("postgres", "http://polestar.ai/rgm/", "Customer", D.MAP.Customer, "rgm");
    expect(pg).toContain('"rgm_gold"."dim_customer"');
    expect(pg).toContain('ontoforge_iri_encode("customer_id"::text)');
    expect(pg).not.toContain("`");
    expect(pg.split("UNION ALL")).toHaveLength(1 + Object.keys(D.MAP.Customer.cols).length);
  });
  it("wraps a SQL-backed class as a subquery", () => {
    expect(compileClassSql("postgres", "http://polestar.ai/rgm/", "KeyAccount", D.MAP.KeyAccount)).toContain("(SELECT * FROM dim_customer WHERE is_key_account = true) AS q");
  });
});

describe("MockApi", () => {
  it("reports the source in the config and denies the catalog when configured", async () => {
    expect((await new MockApi({ sourceKind: "postgres" }).config())).toMatchObject({ sourceKind: "postgres", catalog: null, authHeader: "X-Actor" });
    expect((await new MockApi({ sourceKind: "databricks" }).config())).toMatchObject({ sourceKind: "databricks", catalog: "finops_metadata", authHeader: "X-Forwarded-Email" });
    await expect(new MockApi({ sourceKind: "databricks", catalogDenied: true }).catalogTables("rgm", "gold")).rejects.toThrow(/INSUFFICIENT_PERMISSIONS/);
    const denied = await new MockApi({ sourceKind: "databricks", catalogDenied: true, latency: 0 }).testConnection();
    expect(denied.ok).toBe(false); expect(denied.action).toMatch(/USE CATALOG/);
  });
  it("moves a version through the lifecycle and keeps one active version", async () => {
    const api = new MockApi();
    let d = await api.transition("rgm", 3, "in_review");
    expect(d.versions.find(v => v.version === 3)?.status).toBe("in_review");
    await expect(api.transition("rgm", 2, "published")).rejects.toThrow(/needs 3 approval/);
    await api.review("rgm", 2, true);
    d = await api.transition("rgm", 2, "published");
    d = await api.transition("rgm", 2, "active");
    expect(d.versions.filter(v => v.active).map(v => v.version)).toEqual([2]);
    d = await api.createDraft("rgm", 1);
    expect(d.versions[0]).toMatchObject({ version: 4, status: "draft", lease: { holder: "alice" } });
  });
  it("rejects invalid or duplicate domain names", async () => {
    const api = new MockApi();
    await expect(api.createDomain({ name: "bad name", description: "", base_iri: "http://x/", quorum: 1 })).rejects.toThrow(/letters, digits/);
    await expect(api.createDomain({ name: "rgm", description: "", base_iri: "http://x/", quorum: 1 })).rejects.toThrow(/already exists/);
    await expect(api.createDomain({ name: "supply", description: "", base_iri: "http://x/", quorum: 1 })).rejects.toThrow(/AI connection/);
    const d = await api.createDomain({ name: "supply", description: "Supply chain", base_iri: "http://x/supply/", quorum: 2, ai_connection_id: "c-gpt" });
    expect(d.versions).toEqual([]);
    expect((await api.domains()).map(x => x.name)).toContain("supply");
  });
  it("runs a build step by step and can be cancelled", async () => {
    vi.useFakeTimers();
    try {
      const api = new MockApi({ stepScale: 1 });
      const run = await api.startBuild("rgm", 3);
      expect(run.status).toBe("running"); expect(run.steps[0].state).toBe("running");
      await vi.advanceTimersByTimeAsync(1000);
      let r = await api.buildStatus(run.id);
      expect(r.steps.filter(s => s.state === "done").length).toBeGreaterThan(0);
      expect(r.status).toBe("running");
      await vi.advanceTimersByTimeAsync(5000);
      r = await api.buildStatus(run.id);
      expect(r.status).toBe("succeeded"); expect(r.triples).toBe("263,695"); expect(r.steps.every(s => s.state === "done")).toBe(true);
      expect((await api.builds("rgm", 3))[0].id).toBe(run.id);
      const run2 = await api.startBuild("rgm", 3);
      const cancelled = await api.cancelBuild(run2.id);
      expect(cancelled.status).toBe("cancelled");
      await vi.advanceTimersByTimeAsync(10000);
      expect((await api.buildStatus(run2.id)).status).toBe("cancelled");
    } finally { vi.useRealTimers(); }
  });
  it("filters and sorts triples", async () => {
    const api = new MockApi();
    const inferred = await api.triples("rgm", { q: "", filter: "inferred", sort: "subject", dir: "asc", limit: 100, offset: 0 });
    expect(inferred.rows.every(r => r.inferred)).toBe(true);
    const desc = await api.triples("rgm", { q: "", filter: "all", sort: "object", dir: "desc", limit: 100, offset: 0 });
    const objs = desc.rows.map(r => r.o);
    expect(objs).toEqual([...objs].sort().reverse());
    const text = await api.triples("rgm", { q: "carrefour", filter: "all", sort: "subject", dir: "asc", limit: 100, offset: 0 });
    expect(text.rows).toHaveLength(1);
  });
});

describe("Ask", () => {
  const ctx = async (kind: "databricks" | "postgres" = "databricks") => { const api = new MockApi({ sourceKind: kind }); return { domain: "rgm", domains: await api.domains(), glossary: await api.glossary("rgm"), classes: await api.ontology("rgm", 3), mapping: await api.mapping("rgm", 3), sourceKind: kind }; };
  it("answers a glossary question with the term and links", async () => {
    const a = answer("What is net revenue?", await ctx());
    expect(a.term?.term).toBe("Net revenue"); expect(a.text).toContain("marc"); expect(a.links.map(l => l.screen)).toEqual(["explore", "quality"]);
  });
  it("routes a mapping question to the designer with the class preselected", async () => {
    const a = answer("Where do I map Channel?", await ctx());
    expect(a.links[0]).toMatchObject({ screen: "mapping", params: { cls: "Channel" } }); expect(a.text).toContain("unmapped");
  });
  it("describes another domain and names the running adapter in build answers", async () => {
    expect(answer("Show hr domain", await ctx()).links[0]).toMatchObject({ screen: "overview", domain: "hr" });
    expect(answer("how does a build work", await ctx("postgres")).text).toContain("Postgres SQL");
  });
});

describe("connections and domain settings (mock)", () => {
  it("lists the four connector specs and seeds a warehouse + AI connection", async () => {
    const api = new MockApi();
    expect((await api.connectors()).map(s => s.kind).sort()).toEqual(["azure_openai", "databricks", "postgres", "sqlserver"]);
    const cs = await api.connections();
    expect(cs.map(c => c.kind)).toEqual(["databricks", "postgres", "azure_openai"]);
    expect((await new MockApi({ sourceKind: "postgres" }).connections())[0].kind).toBe("postgres");
  });
  it("tests a seeded connection, attaches it to a domain and detaches it", async () => {
    const api = new MockApi({ latency: 0 });
    const t = await api.testConnectionById("c-warehouse"); expect(t.ok).toBe(true);
    const d = await api.updateDomain("hr", { connection_id: "c-warehouse", default_schema: "people", materialization: "table", target_schema: "hr_graph" });
    expect(d.connectionId).toBe("c-warehouse");
    const f = await api.sourceFacts("hr");
    expect(f).toMatchObject({ kind: "databricks", connection: "warehouse", schema: "people", materialization: "table", target_schema: "hr_graph" });
    await api.detachConnection("c-warehouse");
    expect((await api.sourceFacts("hr")).connection).toBeNull();
    await expect(api.updateDomain("hr", { materialization: "sideways" as never })).rejects.toThrow(/materialization/);
  });
});

describe("version mechanism (mock)", () => {
  it("counts approvals per reviewer and refuses to publish before the quorum", async () => {
    const api = new MockApi();
    let d = await api.review("rgm", 2, true);                       // priya, marc already approved; quorum 3
    const v2 = () => d.versions.find(v => v.version === 2)!;
    expect(v2().review).toMatchObject({ approved: 3, quorum: 3 });
    expect(v2().review!.rows.find(r => r.who === "alice")?.state).toBe("approved");
    d = await api.review("rgm", 2, true);                            // same reviewer twice counts once
    expect(v2().review!.approved).toBe(3);
    await api.transition("rgm", 3, "in_review");
    await expect(api.transition("rgm", 3, "published")).rejects.toThrow(/needs 3 approval/i);
    d = await api.transition("rgm", 2, "published");
    expect(v2().status).toBe("published");
  });
  it("rejecting records the comment and sends the version back to draft", async () => {
    const api = new MockApi();
    await api.transition("rgm", 3, "in_review");                     // no other draft, so v2 could be reopened... use v3
    const d = await api.review("rgm", 3, false, "Channel is unmapped");
    const v3 = d.versions.find(v => v.version === 3)!;
    expect(v3.status).toBe("draft");
    expect(v3.review).toBeNull();
    expect((await api.comments("rgm")).at(-1)).toMatchObject({ who: "alice", text: "Rejected: Channel is unmapped" });
  });
  it("releases, takes and force-takes the edit lease", async () => {
    const api = new MockApi();
    let d = await api.releaseLease("rgm", 3);
    expect(d.versions[0].lease).toBeNull();
    d = await api.takeLease("rgm", 3);
    expect(d.versions[0].lease).toMatchObject({ holder: "alice" });
    d = await api.takeLease("rgm", 3, true);
    expect(d.versions[0].lease).toMatchObject({ holder: "alice" });
    expect(d.lease).toMatchObject({ holder: "alice" });
  });
  it("deletes a draft and nothing else", async () => {
    const api = new MockApi();
    await expect(api.deleteDraft("rgm", 1)).rejects.toThrow(/only draft/i);
    const d = await api.deleteDraft("rgm", 3);
    expect(d.versions.map(v => v.version)).toEqual([2, 1]);
    expect(d.lease).toBeNull();
  });
});

describe("version mechanism (rest)", () => {
  const summary = [
    { id: "v3", version: 3, status: "draft", has_ontology: true, has_mapping: true, rule_count: 2, constraint_count: 7, created_at: "2026-09-18T10:00:00Z", created_by: "alice", is_active: false,
      stats: { classes: 12, attributes: 52, relationships: 11, bindings: 41, rules: 2, constraints: 7, triples: 0 }, mapping: { completion: 0.7812, classes_mapped: 10, classes: 12, complete_classes: 9 },
      last_build: { id: "b1", status: "failed", started_at: "2026-09-20T09:00:00Z", finished_at: "2026-09-20T09:01:00Z", triple_count: null, error: "boom" },
      review: null, lease: { holder: "alice", expires_at: "2026-09-21T10:42:00Z", expired: false } },
    { id: "v2", version: 2, status: "in_review", has_ontology: true, has_mapping: true, rule_count: 2, constraint_count: 6, created_at: "2026-09-12T10:00:00Z", created_by: "marc", is_active: false,
      stats: { classes: 10, attributes: 47, relationships: 9, bindings: 47, rules: 2, constraints: 6, triples: 258102 }, mapping: { completion: 1, classes_mapped: 10, classes: 10, complete_classes: 10 },
      last_build: { id: "b0", status: "succeeded", started_at: "2026-09-16T09:00:00Z", finished_at: "2026-09-16T09:03:00Z", triple_count: 258102, error: null },
      review: { quorum: 3, round: 1, approved: 2, rejected: 0, rows: [{ reviewer: "priya", approved: true, comment: "reviewed mapping", at: "2026-09-17T10:00:00Z" }, { reviewer: "marc", approved: true, comment: null, at: "2026-09-17T11:00:00Z" }] }, lease: null },
    { id: "v1", version: 1, status: "published", has_ontology: true, has_mapping: true, rule_count: 1, constraint_count: 5, created_at: "2026-08-21T10:00:00Z", created_by: "alice", is_active: true,
      stats: { classes: 9, attributes: 44, relationships: 8, bindings: 44, rules: 1, constraints: 5, triples: 241880 }, mapping: { completion: 1, classes_mapped: 9, classes: 9, complete_classes: 9 },
      last_build: { id: "b-1", status: "succeeded", started_at: "2026-09-09T09:00:00Z", finished_at: "2026-09-09T09:03:00Z", triple_count: 241880, error: null },
      review: { quorum: 3, round: 1, approved: 3, rejected: 0, rows: [] }, lease: null },
  ];
  const routes: Record<string, unknown> = {
    "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
    "GET /api/domains/rgm": { name: "rgm", description: "Revenue growth management", base_iri: "http://p/rgm/", review_quorum: 3, active_version_id: "v1" },
    "GET /api/domains/rgm/versions/summary": summary,
    "GET /api/domains/cards": [{ name: "rgm", version_count: 3, active_version: { version: 1 }, latest_version: { version: 3, status: "draft" }, triples: 241880, last_build: null, source: { kind: "databricks", connection: null, catalog: "rgm", schema: "gold" }, mcp: { exposed: true, disabled_tools: [] } }],
    "GET /api/versions/v3/audit": [{ actor: "alice", action: "lease.acquired", created_at: "2026-09-21T10:27:00Z", detail: { forced: false } }, { actor: "alice", action: "version.created", created_at: "2026-09-18T10:00:00Z", detail: {} }],
    "GET /api/versions/v2/audit": [], "GET /api/versions/v1/audit": [],
  };
  const calls: string[] = [];
  const api = () => {
    calls.length = 0;
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`; calls.push(key + (init?.body ? " " + init.body : ""));
      if (key.startsWith("POST /api/versions/v2/reviews")) return new Response(JSON.stringify({ id: 1 }), { status: 201 });
      if (key.startsWith("POST /api/versions/v3/lease") || key.startsWith("POST /api/versions/v3/transition") || key.startsWith("POST /api/versions/v2/transition")) return new Response(JSON.stringify(summary[0]));
      if (key.startsWith("DELETE /api/versions/v3")) return new Response(null, { status: 204 });
      if (key === "POST /api/domains/rgm/active") return new Response(JSON.stringify(routes["GET /api/domains/rgm"]));
      const hit = routes[key]; if (hit === undefined) return new Response(JSON.stringify({ detail: `no route ${key}` }), { status: 404 });
      return new Response(JSON.stringify(hit));
    }) as typeof fetch;
    return new RestApi({ base: "/api" });
  };
  it("maps the summary onto the UI version model", async () => {
    const d = await api().domain("rgm");
    expect(d.versions.map(v => v.version)).toEqual([3, 2, 1]);
    const [v3, v2, v1] = d.versions;
    expect(v3).toMatchObject({ mappingPct: 78, active: false, by: "alice", stats: { classes: 12, attrs: 52, rels: 11, bindings: 41, rules: 2, constraints: 7, triples: 0 }, lease: { holder: "alice" } });
    expect(v3.lastBuild).toMatch(/^failed/);
    expect(v3.content).toBe("ontology · mapping 78% · 2 rules · 7 constraints");
    expect(v3.changes).toEqual(expect.arrayContaining([{ sign: "+", text: "2 classes" }, { sign: "+", text: "5 attributes" }, { sign: "+", text: "1 constraint" }]));
    expect(v2.review).toMatchObject({ approved: 2, quorum: 3, rows: [{ who: "priya", note: "reviewed mapping", state: "approved" }, { who: "marc", note: "", state: "approved" }] });
    expect(v2.lastBuild).toMatch(/^succeeded/);
    expect(v1.active).toBe(true);
    expect(d.review).toMatchObject({ approved: 2, quorum: 3 });          // the version in review
    expect(d.lease).toMatchObject({ holder: "alice" });                 // the draft's lease
  });
  it("calls the lifecycle endpoints with the version ids it learnt", async () => {
    const a = api(); await a.domain("rgm");
    await a.review("rgm", 2, false, "rename Sale");
    expect(calls).toContain('POST /api/versions/v2/reviews {"approved":false,"comment":"rename Sale"}');
    expect(calls).toContain('POST /api/versions/v2/transition {"to":"draft"}');
    await a.takeLease("rgm", 3, true);
    expect(calls).toContain('POST /api/versions/v3/lease {"ttl_seconds":900,"force":true}');
    await a.releaseLease("rgm", 3);
    expect(calls).toContain("DELETE /api/versions/v3/lease");
    await a.deleteDraft("rgm", 3);
    expect(calls).toContain("DELETE /api/versions/v3");
    await a.transition("rgm", 1, "active");
    expect(calls).toContain('POST /api/domains/rgm/active {"version_id":"v1"}');
  });
  it("renders audit actions as sentences with relative times", async () => {
    const rows = await api().audit("rgm");
    expect(rows[0]).toMatchObject({ who: "alice", what: "took the lease on", version: 3 });
    expect(rows[1].what).toBe("created draft");
    expect(rows[1].when).toMatch(/ago$/);
  });
});

describe("several schemas per domain", () => {
  it("mock: keeps an ordered list whose first entry is the default, and lists the source's schemas", async () => {
    const api = new MockApi();
    expect((await api.domain("rgm")).schemas).toEqual(["gold", "silver"]);
    let d = await api.updateDomain("rgm", { schemas: ["silver", "gold", "bronze"] });
    expect(d.schemas).toEqual(["silver", "gold", "bronze"]); expect(d.schema).toBe("silver");
    expect((await api.schemas("rgm")).map(s => s.id)).toEqual(["rgm.silver", "rgm.gold", "rgm.bronze"]);
    expect((await api.schemas("rgm"))[0].label).toBe("warehouse · rgm.silver");
    d = await api.updateDomain("rgm", { default_schema: "bronze" });
    expect(d.schemas).toEqual(["bronze", "silver", "gold"]);
    expect((await api.sourceFacts("rgm")).schemas).toEqual(["bronze", "silver", "gold"]);
    expect(await api.catalogSchemas("rgm")).toEqual(expect.arrayContaining(["gold", "silver", "bronze"]));
  });
  it("rest: reads the list from the domain and the source's schemas from the catalog", async () => {
    const calls: string[] = [];
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}${init?.body ? " " + init.body : ""}`);
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "postgres", catalog: null } },
        "GET /api/domains/hr": { name: "hr", description: "", base_iri: "http://p/hr/", review_quorum: 1, schemas: ["people", "payroll"], default_schema: "people" },
        "GET /api/domains/hr/versions/summary": [],
        "GET /api/domains/cards": [{ name: "hr", version_count: 0, active_version: null, latest_version: null, triples: 0, last_build: null, source: { kind: "postgres", connection: null, catalog: null, schema: "people", schemas: ["people", "payroll"] }, mcp: { exposed: true, disabled_tools: [] } }],
        "GET /api/catalog/schemas": ["people", "payroll", "public"],
        "GET /api/domains/hr/source": { kind: "postgres", connection: null, connection_id: null, catalog: null, schema: "people", schemas: ["people", "payroll"], host: null, auth_mode: "header", auth_header: "X-Actor", materialization: "none", target_schema: null, last_test: null, ai: null, sources: [{ kind: "postgres", connection: null, connection_id: null, catalog: null, schemas: ["people", "payroll"], host: null, last_test: null }] },
      };
      const key = `${init?.method ?? "GET"} ${url}`;
      if (key.startsWith("PUT /api/domains/hr")) return new Response(JSON.stringify(routes["GET /api/domains/hr"]));
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const api = new RestApi({ base: "/api" });
    const d = await api.domain("hr");
    expect(d.schemas).toEqual(["people", "payroll"]); expect(d.schema).toBe("people");
    expect((await api.schemas("hr")).map(s => [s.id, s.label])).toEqual([["people", "deployment default · people"], ["payroll", "deployment default · payroll"]]);
    expect(await api.catalogSchemas("hr")).toEqual(["people", "payroll", "public"]);
    await api.updateDomain("hr", { schemas: ["payroll", "people"] });
    expect(calls).toContain('PUT /api/domains/hr {"schemas":["payroll","people"]}');
  });
});


describe("several sources per domain", () => {
  it("mock: a domain lists sources (connection + catalog + schemas), the first being the primary", async () => {
    const api = new MockApi();
    let d = await api.domain("rgm");
    expect(d.sources).toEqual([{ connectionId: "c-warehouse", catalog: "rgm", schemas: ["gold", "silver"] }]);
    d = await api.updateDomain("rgm", { sources: [{ connection_id: "c-warehouse", catalog: "rgm", schemas: ["gold"] }, { connection_id: "c-lake", catalog: null, schemas: ["raw", "staging"] }] });
    expect(d.sources.map(s => s.connectionId)).toEqual(["c-warehouse", "c-lake"]);
    expect(d).toMatchObject({ connectionId: "c-warehouse", catalog: "rgm", schema: "gold", schemas: ["gold"] });
    await expect(api.updateDomain("rgm", { sources: [{ connection_id: "c-lake", catalog: null, schemas: [] }, { connection_id: "c-lake", catalog: null, schemas: [] }] })).rejects.toThrow(/twice/);
    await expect(api.updateDomain("rgm", { sources: [{ connection_id: "c-nope", catalog: null, schemas: [] }] })).rejects.toThrow(/not found/);
    await expect(api.updateDomain("rgm", { ai_connection_id: null })).rejects.toThrow(/AI connection/);
    const f = await api.sourceFacts("rgm");
    expect(f.sources?.map(s => [s.connection, s.schemas])).toEqual([["warehouse", ["gold"]], ["lake", ["raw", "staging"]]]);
    expect((await api.schemas("rgm")).map(s => s.label)).toEqual(["warehouse · rgm.gold", "lake · raw", "lake · staging"]);
    expect((await api.catalogTables("rgm", "rgm.gold")).length).toBeGreaterThan(0);   // catalog-qualified ids browse the same tables
    await api.detachConnection("c-lake");
    expect((await api.domain("rgm")).sources.map(s => s.connectionId)).toEqual(["c-warehouse"]);
  });
  it("rest: maps the backend's sources and sends the AI connection and sources on create", async () => {
    const calls: string[] = [];
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}${init?.body ? " " + init.body : ""}`);
      const dom = { name: "hr", description: "", base_iri: "http://p/hr/", review_quorum: 1, ai_connection_id: "ai-1", sources: [{ connection_id: "wh", catalog: "rgm", schemas: ["gold", "silver"] }, { connection_id: "lake", catalog: null, schemas: ["raw"] }], connection_id: "wh", default_catalog: "rgm", schemas: ["gold", "silver"], default_schema: "gold" };
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/hr": dom, "GET /api/domains/hr/versions/summary": [],
        "GET /api/domains/cards": [{ name: "hr", version_count: 0, active_version: null, latest_version: null, triples: 0, last_build: null, source: { kind: "databricks", connection: "warehouse", catalog: "rgm", schema: "gold", schemas: ["gold", "silver"] }, source_count: 2, mcp: { exposed: true, disabled_tools: [] } }],
        "GET /api/domains/hr/source": { kind: "databricks", connection: "warehouse", connection_id: "wh", catalog: "rgm", schema: "gold", schemas: ["gold", "silver"], host: null, auth_mode: "header", auth_header: "X-Actor", materialization: "none", target_schema: null, last_test: null, ai: null, connections_backend: "hub",
          sources: [{ kind: "databricks", connection: "warehouse", connection_id: "wh", catalog: "rgm", schemas: ["gold", "silver"], host: null, last_test: null, missing_connection_id: null }, { kind: "postgres", connection: "lake", connection_id: "lake", catalog: null, schemas: ["raw"], host: null, last_test: null, missing_connection_id: null }] },
      };
      const key = `${init?.method ?? "GET"} ${url}`;
      if (key === "POST /api/domains") return new Response(JSON.stringify(dom), { status: 201 });
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const api = new RestApi({ base: "/api" });
    const d = await api.domain("hr");
    expect(d.sources).toEqual([{ connectionId: "wh", catalog: "rgm", schemas: ["gold", "silver"] }, { connectionId: "lake", catalog: null, schemas: ["raw"] }]);
    expect(d).toMatchObject({ connectionId: "wh", aiConnectionId: "ai-1", catalog: "rgm", schema: "gold" });
    expect((await api.schemas("hr")).map(s => [s.id, s.label])).toEqual([["rgm.gold", "warehouse · rgm.gold"], ["rgm.silver", "warehouse · rgm.silver"], ["raw", "lake · raw"]]);
    await api.createDomain({ name: "hr", description: "", base_iri: "http://p/hr/", quorum: 1, ai_connection_id: "ai-1", sources: [{ connection_id: "wh", catalog: null, schemas: [] }] });
    expect(calls).toContain('POST /api/domains {"name":"hr","description":"","base_iri":"http://p/hr/","review_quorum":1,"ai_connection_id":"ai-1","sources":[{"connection_id":"wh","catalog":null,"schemas":[]}]}');
  });
});
