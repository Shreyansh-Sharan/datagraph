import { describe, expect, it, vi } from "vitest";
import { MockApi } from "@/api/mock";
import { askTerm } from "@/api";
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
  const ctx = async (kind: "databricks" | "postgres" = "databricks") => { const api = new MockApi({ sourceKind: kind }); return { domain: "rgm", domains: await api.domains(), glossary: (await api.glossary("rgm")).map(askTerm), classes: await api.ontology("rgm", 3), mapping: await api.mapping("rgm", 3), sourceKind: kind }; };
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
    expect((await api.schemas("rgm"))[0]).toMatchObject({ label: "rgm.silver", group: "warehouse" });
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
        "GET /api/catalog/schemas?domain=hr": ["people", "payroll", "public"],
        "GET /api/domains/hr/source": { kind: "postgres", connection: null, connection_id: null, catalog: null, schema: "people", schemas: ["people", "payroll"], host: null, auth_mode: "header", auth_header: "X-Actor", materialization: "none", target_schema: null, last_test: null, ai: null, sources: [{ kind: "postgres", connection: null, connection_id: null, catalog: null, schemas: ["people", "payroll"], host: null, last_test: null }] },
      };
      const key = `${init?.method ?? "GET"} ${url}`;
      if (key.startsWith("PUT /api/domains/hr")) return new Response(JSON.stringify(routes["GET /api/domains/hr"]));
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const api = new RestApi({ base: "/api" });
    const d = await api.domain("hr");
    expect(d.schemas).toEqual(["people", "payroll"]); expect(d.schema).toBe("people");
    expect((await api.schemas("hr")).map(s => [s.id, s.label, s.group])).toEqual([["people", "people", "deployment default"], ["payroll", "payroll", "deployment default"]]);
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
    expect((await api.schemas("rgm")).map(s => `${s.group} · ${s.label}`)).toEqual(["warehouse · rgm.gold", "lake · raw", "lake · staging"]);
    expect((await api.catalogTables("rgm", "rgm.gold")).length).toBeGreaterThan(0);   // catalog-qualified ids browse the same tables
    await api.detachConnection("c-lake");
    expect((await api.domain("rgm")).sources.map(s => s.connectionId)).toEqual(["c-warehouse"]);
    // a source with no schema chosen browses every schema the source offers
    await api.updateDomain("rgm", { sources: [{ connection_id: "c-warehouse", catalog: "rgm", schemas: [] }] });
    expect((await api.schemas("rgm")).map(s => s.id)).toEqual(["rgm.gold", "rgm.silver", "rgm.bronze"]);
  });
  it("rest: maps the backend's sources and sends the AI connection and sources on create", async () => {
    const calls: string[] = [];
    const dom = { name: "hr", description: "", base_iri: "http://p/hr/", review_quorum: 1, ai_connection_id: "ai-1", sources: [{ connection_id: "wh", catalog: "rgm", schemas: ["gold", "silver"] }, { connection_id: "lake", catalog: null, schemas: ["raw"] }], connection_id: "wh", default_catalog: "rgm", schemas: ["gold", "silver"], default_schema: "gold" };
    const routes: Record<string, unknown> = {
        "GET /api/catalog/schemas?domain=hr&catalog=rgm": ["bronze", "gold"],
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/hr": dom, "GET /api/domains/hr/versions/summary": [],
        "GET /api/domains/cards": [{ name: "hr", version_count: 0, active_version: null, latest_version: null, triples: 0, last_build: null, source: { kind: "databricks", connection: "warehouse", catalog: "rgm", schema: "gold", schemas: ["gold", "silver"] }, source_count: 2, mcp: { exposed: true, disabled_tools: [] } }],
        "GET /api/domains/hr/source": { kind: "databricks", connection: "warehouse", connection_id: "wh", catalog: "rgm", schema: "gold", schemas: ["gold", "silver"], host: null, auth_mode: "header", auth_header: "X-Actor", materialization: "none", target_schema: null, last_test: null, ai: null, connections_backend: "hub",
          sources: [{ kind: "databricks", connection: "warehouse", connection_id: "wh", catalog: "rgm", schemas: ["gold", "silver"], host: null, last_test: null, missing_connection_id: null }, { kind: "postgres", connection: "lake", connection_id: "lake", catalog: null, schemas: ["raw"], host: null, last_test: null, missing_connection_id: null }] },
      };
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}${init?.body ? " " + init.body : ""}`);
      const key = `${init?.method ?? "GET"} ${url}`;
      if (key === "POST /api/domains") return new Response(JSON.stringify(dom), { status: 201 });
      if (key === "GET /api/domains/hr") return new Response(JSON.stringify(dom));
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const api = new RestApi({ base: "/api" });
    const d = await api.domain("hr");
    expect(d.sources).toEqual([{ connectionId: "wh", catalog: "rgm", schemas: ["gold", "silver"] }, { connectionId: "lake", catalog: null, schemas: ["raw"] }]);
    expect(d).toMatchObject({ connectionId: "wh", aiConnectionId: "ai-1", catalog: "rgm", schema: "gold" });
    expect((await api.schemas("hr")).map(s => [s.id, `${s.group} · ${s.label}`])).toEqual([["rgm.gold", "warehouse · rgm.gold"], ["rgm.silver", "warehouse · rgm.silver"], ["raw", "lake · raw"]]);
    // no schema chosen on the primary source: every schema of its catalog is offered
    dom.sources[0].schemas = []; dom.schemas = [];
    (routes["GET /api/domains/hr/source"] as { sources: { schemas: string[] }[] }).sources[0].schemas = [];
    expect((await api.schemas("hr")).map(s => s.id)).toEqual(["rgm.bronze", "rgm.gold", "raw"]);
    expect(calls.filter(c => c.startsWith("GET /api/catalog/schemas?domain=hr&catalog=rgm")).length).toBe(1);
    await api.createDomain({ name: "hr", description: "", base_iri: "http://p/hr/", quorum: 1, ai_connection_id: "ai-1", sources: [{ connection_id: "wh", catalog: null, schemas: [] }] });
    expect(calls).toContain('POST /api/domains {"name":"hr","description":"","base_iri":"http://p/hr/","review_quorum":1,"ai_connection_id":"ai-1","sources":[{"connection_id":"wh","catalog":null,"schemas":[]}]}');
  });
});


describe("metadata snapshot (scan)", () => {
  it("mock: importing tables puts them in the version's snapshot and marks them in the catalog list", async () => {
    const api = new MockApi();
    const before = await api.catalogTables("rgm", "rgm.gold", 3);
    expect(before.filter(t => t.imported).map(t => t.name)).not.toContain("dim_date");
    const snap = await api.importTables("rgm", 3, "rgm.gold", ["dim_date", "fct_returns"]);
    expect(snap.map(t => t.table)).toEqual(expect.arrayContaining(["rgm.gold.dim_date", "rgm.gold.fct_returns"]));
    const after = await api.catalogTables("rgm", "rgm.gold", 3);
    expect(after.find(t => t.name === "dim_date")).toMatchObject({ imported: true });
    expect((await api.snapshot("rgm", 3)).length).toBe(snap.length);
    await expect(api.importTables("hr", 3, "hr.people", ["employees"])).rejects.toThrow(/draft/);
    expect(await api.refreshSnapshot("rgm", 3)).toEqual([]);
  });
  it("rest: imports through the version's metadata endpoint and reads the snapshot back into the list", async () => {
    const calls: string[] = [];
    const snapshot: { table: string; comment: string | null; columns: { name: string; type: string; comment: string | null }[]; primary_key: string[]; foreign_keys: unknown[] }[] = [];
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`; calls.push(key + (init?.body ? " " + init.body : ""));
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/aw": { name: "aw", description: "", base_iri: "http://p/aw/", review_quorum: 1, sources: [{ connection_id: "c1", catalog: "adventurework2022", schemas: [] }] },
        "GET /api/domains/aw/versions/summary": [{ id: "v-1", version: 1, status: "draft", has_ontology: false, has_mapping: false, rule_count: 0, constraint_count: 0, created_at: "2026-09-21T10:00:00Z", created_by: "alice", is_active: false, stats: { classes: 0, attributes: 0, relationships: 0, bindings: 0, rules: 0, constraints: 0, triples: 0 }, mapping: null, last_build: null, review: null, lease: null }],
        "GET /api/domains/cards": [{ name: "aw", version_count: 1, active_version: null, latest_version: { version: 1, status: "draft" }, triples: 0, last_build: null, source: { kind: "databricks", connection: "AdventureWorks", catalog: "adventurework2022", schema: null, schemas: [] }, source_count: 1, mcp: { exposed: true, disabled_tools: [] } }],
        "GET /api/catalog/tables?domain=aw&schema_name=adventurework2022.dbo&detail=true": [{ name: "awbuildversion", columns: 4, comment: null }, { name: "databaselog", columns: 8, comment: null }, { name: "errorlog", columns: 9, comment: null }],
        "GET /api/versions/v-1/metadata": snapshot,
        "POST /api/versions/v-1/metadata/refresh": [{ table: "adventurework2022.dbo.errorlog", missing: false, added: ["severity"], removed: [], modified: [], keys_changed: false }],
      };
      if (key.startsWith("DELETE /api/versions/v-1/metadata/")) {
        const name = decodeURIComponent(key.split("/metadata/")[1]); const i = snapshot.findIndex(t => t.table === name);
        if (i >= 0) snapshot.splice(i, 1);
        return new Response(null, { status: i >= 0 ? 204 : 404 });
      }
      if (key === "POST /api/versions/v-1/metadata/import") {
        const body = JSON.parse(String(init?.body)) as { tables: string[]; schema_name: string };
        for (const t of body.tables) snapshot.push({ table: `${body.schema_name}.${t}`, comment: null, columns: [{ name: "id", type: "int", comment: null }, { name: "v", type: "string", comment: null }], primary_key: ["id"], foreign_keys: [] });
        return new Response(JSON.stringify(snapshot));
      }
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const api = new RestApi({ base: "/api" });
    await api.domain("aw");
    expect((await api.catalogTables("aw", "adventurework2022.dbo", 1)).map(t => t.imported)).toEqual([false, false, false]);
    const snap = await api.importTables("aw", 1, "adventurework2022.dbo", ["errorlog", "databaselog"]);
    expect(calls).toContain('POST /api/versions/v-1/metadata/import {"tables":["errorlog","databaselog"],"schema_name":"adventurework2022.dbo"}');
    expect(snap.map(t => [t.table, t.columns])).toEqual([["adventurework2022.dbo.errorlog", 2], ["adventurework2022.dbo.databaselog", 2]]);
    const after = await api.catalogTables("aw", "adventurework2022.dbo", 1);
    expect(after.map(t => [t.name, t.imported, t.cols])).toEqual([["awbuildversion", false, 4], ["databaselog", true, 8], ["errorlog", true, 9]]);
    expect((await api.refreshSnapshot("aw", 1))[0]).toMatchObject({ table: "adventurework2022.dbo.errorlog", added: ["severity"] });
    expect(after.find(t => t.name === "errorlog")?.held).toBe("adventurework2022.dbo.errorlog");          // the snapshot's own name, for removal
    await api.removeTable("aw", 1, "adventurework2022.dbo.errorlog");
    expect(calls).toContain("DELETE /api/versions/v-1/metadata/adventurework2022.dbo.errorlog");
    expect((await api.catalogTables("aw", "adventurework2022.dbo", 1)).map(t => t.imported)).toEqual([false, true, false]);
  });
});


describe("build (rest)", () => {
  const vid = "11111111-2222-3333-4444-555555555555", rid = "5e255332-aaaa-bbbb-cccc-dddddddddddd";
  const running = { id: rid, status: "running", actor: "alice", started_at: "2026-09-21T12:00:00Z", finished_at: null, triple_count: null, error: null, steps: [{ name: "compile", seconds: 0.41, detail: { selects: 3 } }, { name: "drift", seconds: null }] };
  const failed = { ...running, status: "failed", finished_at: "2026-09-21T12:00:01Z", error: "BuildError: Version has neither a mapping spec nor an R2RML document", steps: [{ name: "compile", seconds: 0.1 }] };
  const calls: string[] = [];
  const api = (run: unknown) => {
    calls.length = 0;
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`; calls.push(key);
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/aw": { name: "aw", description: "", base_iri: "http://p/aw/", review_quorum: 1, materialization: "none", sources: [] },
        "GET /api/domains/aw/versions/summary": [{ id: vid, version: 1, status: "draft", has_ontology: true, has_mapping: false, rule_count: 0, constraint_count: 0, created_at: "2026-09-21T10:00:00Z", created_by: "alice", is_active: false, stats: { classes: 4, attributes: 9, relationships: 2, bindings: 0, rules: 0, constraints: 0, triples: 0 }, mapping: { completion: 0.25, classes_mapped: 1, classes: 4, complete_classes: 0 }, last_build: null, review: null, lease: null }],
        "GET /api/domains/cards": [{ name: "aw", version_count: 1, active_version: null, latest_version: { version: 1, status: "draft" }, triples: 0, last_build: null, source: { kind: "databricks", connection: null, catalog: null, schema: null, schemas: [] }, source_count: 0, mcp: { exposed: true, disabled_tools: [] } }],
        [`GET /api/versions/${vid}/builds`]: [run], [`GET /api/builds/${rid}`]: run, [`POST /api/versions/${vid}/builds`]: run,
        [`GET /api/versions/${vid}/ontology`]: { classes: [{}, {}, {}, {}] }, [`GET /api/versions/${vid}/ontology/checks`]: [{ severity: "error" }, { severity: "warning" }],
        [`GET /api/versions/${vid}/mapping/status`]: { completion: 0.25, summary: { classes: 4, mapped_classes: 1, complete_classes: 0, attributes: 9, mapped_attributes: 2, excluded_attributes: 1, relations: 2, mapped_relations: 0, excluded_relations: 0 }, classes: [] },
        [`GET /api/versions/${vid}/mapping/drift`]: [{ table: "t" }], [`GET /api/versions/${vid}/metadata`]: [{ table: "a" }, { table: "b" }],
      };
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    return new RestApi({ base: "/api" });
  };
  it("keeps the full run id for polling and shows a short label, with live steps and the queued rest of the pipeline", async () => {
    const a = api(running); await a.domain("aw");
    const r = (await a.builds("aw", 1))[0];
    expect(r.id).toBe(rid); expect(r.label).toBe("#5e25"); expect(r.status).toBe("running");
    expect(r.steps.map(s => [s.name, s.state])).toEqual([["compile", "done"], ["drift", "running"], ["prepare", "queued"], ["load", "queued"], ["finalize", "queued"]]);
    expect(r.steps[0].detail).toBe("3 selects"); expect(r.stepIndex).toBe(1);
    await a.buildStatus(r.id);
    expect(calls).toContain(`GET /api/builds/${rid}`);
  });
  it("shows the rows loaded so far on a running load step", async () => {
    const loading = { ...running, steps: [{ name: "compile", seconds: 0.41, detail: { selects: 3 } }, { name: "prepare", seconds: 0 }, { name: "load", seconds: null, detail: { rows: 123456 } }] };
    const a = api(loading); await a.domain("aw");
    const r = (await a.builds("aw", 1))[0];
    expect(r.steps.map(s => [s.name, s.state])).toEqual([["compile", "done"], ["prepare", "done"], ["load", "running"], ["finalize", "queued"]]);
    expect(r.steps[2].detail).toBe("123,456 rows so far");
  });
  it("points at the next queued step and shows elapsed time when an older API reports no running step", async () => {
    const between = { ...running, started_at: new Date(Date.now() - 95_000).toISOString(), steps: [{ name: "compile", seconds: 0.41 }, { name: "drift", seconds: 1 }, { name: "prepare", seconds: 0 }] };
    const a = api(between); await a.domain("aw");
    const r = (await a.builds("aw", 1))[0];
    expect(r.steps.map(s => s.state)).toEqual(["done", "done", "done", "queued", "queued"]);
    expect(r.stepIndex).toBe(3);
    expect(r.duration).toMatch(/^1 min 3[0-9] s so far$/);
  });
  it("reports a failed run with its error and no running step", async () => {
    const a = api(failed); await a.domain("aw");
    const r = (await a.builds("aw", 1))[0];
    expect(r.status).toBe("failed"); expect(r.error).toMatch(/neither a mapping spec/); expect(r.stepIndex).toBe(-1); expect(r.duration).toBe("1.0 s");
    expect(r.steps.map(s => s.state)).toEqual(["done"]);
  });
  it("builds the pre-build checklist and mapping KPIs from the version's real state", async () => {
    const a = api(failed); await a.domain("aw");
    const items = await a.checklist("aw", 1);
    expect(items.map(i => [i.label, i.value, i.ok])).toEqual([["Snapshot", "2 tables", true], ["Ontology", "4 classes", true], ["Mapping completion", "25%", false], ["Ontology checks", "1 error", false]]);   // drift is the Build screen's own row
    expect(await a.mappingKpis("aw", 1)).toEqual({ completion: 25, classesMapped: [1, 4], attributes: [2, 9], relationships: [0, 2], excluded: 1 });
  });
});


describe("mapping editor (rest)", () => {
  const vid = "aaaaaaaa-0000-0000-0000-000000000001";
  const EX = "http://p/aw#";
  const onto = { classes: [{ iri: EX + "Customer", label: "Customer", description: null, parents: [] }, { iri: EX + "Order", label: "Order", description: null, parents: [] }],
    datatype_properties: [{ iri: EX + "customerName", domain: EX + "Customer", domains: [EX + "Customer"], range: "http://www.w3.org/2001/XMLSchema#string" }, { iri: EX + "orderDate", domain: EX + "Order", domains: [EX + "Order"], range: null }],
    object_properties: [{ iri: EX + "placedBy", domain: EX + "Order", domains: [EX + "Order"], range: EX + "Customer" }] };
  let spec: { base_iri: string; classes: Record<string, unknown>[]; relations: Record<string, unknown>[] } = { base_iri: "http://p/aw/", classes: [], relations: [] };
  const puts: unknown[] = []; const calls: string[] = [];
  const api = () => {
    spec = { base_iri: "http://p/aw/", classes: [{ class_iri: EX + "Customer", table: "adventurework2022.sales.customer", sql_query: null, key_columns: ["customerid"], iri_template: null, attributes: [{ property_iri: EX + "customerName", column: "name", datatype: null, language: null }], excluded: [] }], relations: [] };
    puts.length = 0; calls.length = 0;
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`; calls.push(key);
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/aw": { name: "aw", description: "", base_iri: "http://p/aw/", review_quorum: 1, materialization: "none", sources: [] },
        "GET /api/domains/aw/versions/summary": [{ id: vid, version: 1, status: "draft", has_ontology: true, has_mapping: true, rule_count: 0, constraint_count: 0, created_at: "2026-09-21T10:00:00Z", created_by: "alice", is_active: false, stats: { classes: 2, attributes: 2, relationships: 1, bindings: 1, rules: 0, constraints: 0, triples: 0 }, mapping: { completion: 0.4, classes_mapped: 1, classes: 2, complete_classes: 1 }, last_build: null, review: null, lease: null }],
        "GET /api/domains/cards": [{ name: "aw", version_count: 1, active_version: null, latest_version: { version: 1, status: "draft" }, triples: 0, last_build: null, source: { kind: "databricks", connection: null, catalog: null, schema: null, schemas: [] }, source_count: 0, mcp: { exposed: true, disabled_tools: [] } }],
        [`GET /api/versions/${vid}/ontology`]: onto,
        [`GET /api/versions/${vid}/mapping/status`]: { completion: 0.4, summary: {}, classes: [{ class_iri: EX + "Customer", state: "complete" }, { class_iri: EX + "Order", state: "unmapped" }] },
        [`GET /api/versions/${vid}/mapping/drift`]: [{ kind: "missing-column", table: "adventurework2022.sales.customer", column: "name", detail: "column name no longer exists", mapping_ref: "Customer.customerName", severity: "error" }],
        [`GET /api/versions/${vid}/metadata`]: [{ table: "adventurework2022.sales.customer", comment: null, columns: [{ name: "customerid", type: "int", comment: null }, { name: "name", type: "string", comment: null }], primary_key: ["customerid"], foreign_keys: [] }, { table: "adventurework2022.sales.salesorderheader", comment: null, columns: [{ name: "salesorderid", type: "int", comment: null }, { name: "customerid", type: "int", comment: null }, { name: "orderdate", type: "date", comment: null }], primary_key: ["salesorderid"], foreign_keys: [] }],
      };
      if (key === `GET /api/versions/${vid}/mapping`) return new Response(JSON.stringify(spec));
      if (key === `PUT /api/versions/${vid}/mapping`) { spec = JSON.parse(String(init?.body)); puts.push(spec); return new Response(JSON.stringify({ id: vid })); }
      if (key === `GET /api/versions/${vid}/mapping/r2rml`) return new Response("@prefix rr: <http://www.w3.org/ns/r2rml#> .", { headers: { "content-type": "text/turtle" } });
      if (key === `POST /api/versions/${vid}/llm/suggest-mapping?background=true`) { return new Response(JSON.stringify({ id: "j1", kind: "suggest-mapping", version_id: vid, status: "succeeded", progress: "Done", result: { classes: 2, relations: 1, mapping: spec }, error: null }), { status: 202 }); }
      if (key.startsWith(`DELETE /api/versions/${vid}/mapping/classes`)) { spec.classes = []; return new Response(JSON.stringify(spec)); }
      if (key === `POST /api/versions/${vid}/mapping/exclude-unmapped`) return new Response(JSON.stringify(spec));
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    return new RestApi({ base: "/api" });
  };
  it("reads bindings, excluded properties, relations and the full table name", async () => {
    const a = api(); await a.domain("aw");
    spec.classes[0] = { ...spec.classes[0], excluded: [EX + "orderDate"] };
    spec.relations = [{ property_iri: EX + "placedBy", source_class: EX + "Order", target_class: EX + "Customer", source_key: ["customerid"], target_key: ["customerid"], table: null, sql_query: null, direction: "forward" }];
    spec.classes.push({ class_iri: EX + "Order", table: "adventurework2022.sales.salesorderheader", sql_query: null, key_columns: ["salesorderid"], iri_template: null, attributes: [], excluded: [] });
    const m = await a.mapping("aw", 1);
    expect(m.Customer).toMatchObject({ fullName: "adventurework2022.sales.customer", table: ["sales", "customer"], key: "customerid", cols: { customerName: "name" }, state: "complete" });
    expect(m.Order.rels).toEqual({ placedBy: "customerid → Customer.customerid" });
    expect(m.Customer.excluded).toEqual(["orderDate"]);
  });
  it("maps a class to a snapshot table, binds and unbinds attributes, excludes, maps a relation and unmaps", async () => {
    const a = api(); await a.domain("aw");
    await a.mapClass("aw", 1, "Order", "adventurework2022.sales.salesorderheader", ["salesorderid"]);
    expect(puts.at(-1)).toMatchObject({ classes: [expect.anything(), { class_iri: EX + "Order", table: "adventurework2022.sales.salesorderheader", key_columns: ["salesorderid"], attributes: [], excluded: [] }] });
    await a.bindAttribute("aw", 1, "Order", "orderDate", "orderdate");
    expect((puts.at(-1) as typeof spec).classes[1]).toMatchObject({ attributes: [{ property_iri: EX + "orderDate", column: "orderdate" }] });
    await a.bindAttribute("aw", 1, "Order", "orderDate", null);
    expect((puts.at(-1) as typeof spec).classes[1]).toMatchObject({ attributes: [] });
    await a.excludeProperty("aw", 1, "Order", "orderDate", true);
    expect((puts.at(-1) as typeof spec).classes[1]).toMatchObject({ excluded: [EX + "orderDate"] });
    await a.mapRelation("aw", 1, "Order", "placedBy", ["salesorderid"], ["customerid"]);   // the order row, and the column holding the customer's key
    expect((puts.at(-1) as typeof spec).relations).toEqual([{ property_iri: EX + "placedBy", source_class: EX + "Order", target_class: EX + "Customer", source_key: ["salesorderid"], target_key: ["customerid"], table: null, sql_query: null, direction: "forward" }]);
    await a.unmapClass("aw", 1, "Order");
    expect(calls).toContain(`DELETE /api/versions/${vid}/mapping/classes?class_iri=${encodeURIComponent(EX + "Order")}`);
    await a.excludeUnmapped("aw", 1);
    expect(calls).toContain(`POST /api/versions/${vid}/mapping/exclude-unmapped`);
  });
  it("lists drift, exports R2RML, suggests with AI and offers snapshot tables with their columns", async () => {
    const a = api(); await a.domain("aw");
    expect((await a.drift("aw", 1))[0]).toMatchObject({ kind: "missing-column", column: "name", mapping_ref: "Customer.customerName" });
    expect(await a.r2rml("aw", 1)).toMatch(/^@prefix rr:/);
    expect(await a.suggestMapping("aw", 1)).toEqual({ classes: 2, relations: 1, skipped: [] });
    const snap = await a.snapshot("aw", 1);
    expect(snap[1]).toMatchObject({ table: "adventurework2022.sales.salesorderheader", columnNames: ["salesorderid", "customerid", "orderdate"], primaryKey: ["salesorderid"] });
  });
});

describe("mapping editor (mock)", () => {
  it("maps Channel to a table, binds its attribute and unmaps it again", async () => {
    const api = new MockApi();
    expect((await api.mapping("rgm", 3)).Channel).toBeUndefined();
    await api.mapClass("rgm", 3, "Channel", "rgm.gold.dim_channel", ["channel_id"]);
    let m = (await api.mapping("rgm", 3)).Channel;
    expect(m).toMatchObject({ fullName: "rgm.gold.dim_channel", key: "channel_id", state: "partial", cols: {} });
    await api.bindAttribute("rgm", 3, "Channel", "channelName", "channel_name");
    m = (await api.mapping("rgm", 3)).Channel;
    expect(m.cols).toEqual({ channelName: "channel_name" }); expect(m.state).toBe("complete");
    await api.excludeProperty("rgm", 3, "Sale", "netRevenue", true);
    expect((await api.mapping("rgm", 3)).Sale.excluded).toEqual(["netRevenue"]);
    await api.unmapClass("rgm", 3, "Channel");
    expect((await api.mapping("rgm", 3)).Channel).toBeUndefined();
    expect((await api.drift("rgm", 3)).length).toBeGreaterThan(0);
    expect(await api.r2rml("rgm", 3)).toMatch(/rr:/);
  });
});


describe("metadata screen data (rest)", () => {
  const vid = "cccccccc-0000-0000-0000-000000000001", EX = "http://p/aw#";
  const api = () => {
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`;
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/aw": { name: "aw", description: "", base_iri: "http://p/aw/", review_quorum: 1, materialization: "none", sources: [{ connection_id: "c1", catalog: "adventurework2022", schemas: ["sales"] }] },
        "GET /api/domains/aw/versions/summary": [{ id: vid, version: 1, status: "draft", has_ontology: true, has_mapping: true, rule_count: 0, constraint_count: 0, created_at: "2026-09-21T10:00:00Z", created_by: "alice", is_active: false, stats: { classes: 1, attributes: 0, relationships: 0, bindings: 0, rules: 0, constraints: 0, triples: 0 }, mapping: null, last_build: null, review: null, lease: null }],
        "GET /api/domains/cards": [{ name: "aw", version_count: 1, active_version: null, latest_version: { version: 1, status: "draft" }, triples: 0, last_build: null, source: { kind: "databricks", connection: "AdventureWorks", catalog: "adventurework2022", schema: "sales", schemas: ["sales"] }, source_count: 1, mcp: { exposed: true, disabled_tools: [] } }],
        "GET /api/catalog/tables?domain=aw&schema_name=adventurework2022.sales&detail=true": [{ name: "customer", columns: 7, comment: "Customers" }, { name: "store", columns: 5, comment: null }],
        [`GET /api/versions/${vid}/metadata`]: [{ table: "adventurework2022.sales.customer", comment: "Customers", columns: [{ name: "customerid", type: "int", comment: null }], primary_key: ["customerid"], foreign_keys: [] }],
        [`GET /api/versions/${vid}/ontology`]: { classes: [{ iri: EX + "Customer", label: "Customer", description: null, parents: [] }], datatype_properties: [], object_properties: [] },
        [`GET /api/versions/${vid}/mapping`]: { base_iri: "http://p/aw/", classes: [{ class_iri: EX + "Customer", table: "adventurework2022.sales.customer", sql_query: null, key_columns: ["customerid"], iri_template: null, attributes: [], excluded: [] }], relations: [] },
        [`GET /api/versions/${vid}/mapping/status`]: { completion: 1, summary: {}, classes: [{ class_iri: EX + "Customer", state: "complete" }] },
      };
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    return new RestApi({ base: "/api" });
  };
  it("lists tables with real column counts, snapshot state and the class each is mapped to", async () => {
    const a = api(); await a.domain("aw");
    const rows = await a.catalogTables("aw", "adventurework2022.sales", 1);
    expect(rows).toEqual([{ name: "customer", cols: 7, imported: true, cls: "Customer", held: "adventurework2022.sales.customer" }, { name: "store", cols: 5, imported: false, cls: null, held: null }]);
    expect(await a.tableClass("aw", "customer", 1)).toBe("Customer");
    expect(await a.tableClass("aw", "store", 1)).toBeNull();
  });
  it("still lists tables when an older backend answers the detail request with bare names", async () => {
    const a = api();
    const inner = globalThis.fetch;
    globalThis.fetch = (async (url: string, init?: RequestInit) => url.includes("/catalog/tables?") ? new Response(JSON.stringify(["customer", "store"])) : inner(url, init)) as typeof fetch;
    await a.domain("aw");
    expect(await a.catalogTables("aw", "adventurework2022.sales", 1)).toEqual([{ name: "customer", cols: 1, imported: true, cls: "Customer", held: "adventurework2022.sales.customer" }, { name: "store", cols: 0, imported: false, cls: null, held: null }]);
  });
  it("says which extras the deployment offers instead of showing design data", async () => {
    const a = api();
    expect((await a.config()).capabilities).toEqual({ profiling: true, quality: true, glossary: true });
    expect((await new MockApi().config()).capabilities).toEqual({ profiling: true, quality: true, glossary: true });
  });
});


describe("ontology drafting", () => {
  it("rest: drafts with AI from the snapshot tables, or from the catalog without AI", async () => {
    const vid = "dddddddd-0000-0000-0000-000000000001"; const calls: string[] = [];
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`; calls.push(key + (init?.body ? " " + init.body : ""));
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/aw": { name: "aw", description: "", base_iri: "http://p/aw/", review_quorum: 1, materialization: "none", sources: [] },
        "GET /api/domains/aw/versions/summary": [{ id: vid, version: 1, status: "draft", has_ontology: false, has_mapping: false, rule_count: 0, constraint_count: 0, created_at: "2026-09-21T10:00:00Z", created_by: "alice", is_active: false, stats: { classes: 0, attributes: 0, relationships: 0, bindings: 0, rules: 0, constraints: 0, triples: 0 }, mapping: null, last_build: null, review: null, lease: null }],
        "GET /api/domains/cards": [{ name: "aw", version_count: 1, active_version: null, latest_version: { version: 1, status: "draft" }, triples: 0, last_build: null, source: { kind: "databricks", connection: null, catalog: null, schema: null, schemas: [] }, source_count: 0, mcp: { exposed: true, disabled_tools: [] } }],
        [`GET /api/versions/${vid}/metadata`]: [{ table: "adventurework2022.sales.customer", comment: null, columns: [{ name: "customerid", type: "int", comment: null }], primary_key: ["customerid"], foreign_keys: [] }, { table: "adventurework2022.sales.salesorderheader", comment: null, columns: [], primary_key: [], foreign_keys: [] }],
        [`POST /api/versions/${vid}/llm/draft-ontology?background=true`]: { id: "j2", kind: "draft-ontology", version_id: vid, status: "succeeded", progress: "Done", result: { classes: 2, properties: 34, issues: [{ severity: "warning" }], ontology: {} }, error: null },
        [`POST /api/versions/${vid}/autodraft`]: { classes: 2, properties: 12, mapping: { classes: 2 } },
      };
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const a = new RestApi({ base: "/api" }); await a.domain("aw");
    expect(await a.draftOntology("aw", 1, { ai: true, description: "Sales" })).toEqual({ classes: 2, properties: 34, warnings: 1 });
    expect(calls).toContain(`POST /api/versions/${vid}/llm/draft-ontology?background=true {"ontology_iri":"http://p/aw/ontology","description":"Sales","tables":["adventurework2022.sales.customer","adventurework2022.sales.salesorderheader"]}`);
    expect(await a.draftOntology("aw", 1, { ai: false, tables: ["adventurework2022.sales.customer"] })).toEqual({ classes: 2, properties: 12, warnings: 0 });
    expect(calls).toContain(`POST /api/versions/${vid}/autodraft {"ontology_iri":"http://p/aw/ontology","tables":["adventurework2022.sales.customer"],"infer_keys":true}`);
  });
  it("mock: drafting fills an empty domain with classes", async () => {
    const api = new MockApi();
    await api.createDomain({ name: "aw", description: "", base_iri: "http://p/aw/", quorum: 1, ai_connection_id: "c-gpt" });
    await api.createDraft("aw");
    expect(await api.ontology("aw", 1)).toEqual([]);
    const r = await api.draftOntology("aw", 1, { ai: true });
    expect(r.classes).toBeGreaterThan(0);
    expect((await api.ontology("aw", 1)).length).toBe(r.classes);
  });
});


describe("AI tasks report progress", () => {
  it("rest: starts a background job, polls it and relays each status until it settles", async () => {
    const vid = "eeeeeeee-0000-0000-0000-000000000001"; let polls = 0;
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`;
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/aw": { name: "aw", description: "", base_iri: "http://p/aw/", review_quorum: 1, materialization: "none", sources: [] },
        "GET /api/domains/aw/versions/summary": [{ id: vid, version: 1, status: "draft", has_ontology: true, has_mapping: false, rule_count: 0, constraint_count: 0, created_at: "2026-09-21T10:00:00Z", created_by: "alice", is_active: false, stats: { classes: 2, attributes: 2, relationships: 1, bindings: 0, rules: 0, constraints: 0, triples: 0 }, mapping: null, last_build: null, review: null, lease: null }],
        "GET /api/domains/cards": [{ name: "aw", version_count: 1, active_version: null, latest_version: { version: 1, status: "draft" }, triples: 0, last_build: null, source: { kind: "databricks", connection: null, catalog: null, schema: null, schemas: [] }, source_count: 0, mcp: { exposed: true, disabled_tools: [] } }],
        [`GET /api/versions/${vid}/metadata`]: [],
      };
      if (key === `POST /api/versions/${vid}/llm/suggest-mapping?background=true`) return new Response(JSON.stringify({ id: "job-1", kind: "suggest-mapping", version_id: vid, status: "running", progress: "Queued", started_at: "2026-09-21T10:00:00Z", progress_at: "2026-09-21T10:00:00Z", finished_at: null, result: null, error: null }), { status: 202 });
      if (key === "GET /api/jobs/job-1") { polls++; const stages = [{ status: "running", progress: "Describing table 3 of 68: customer" }, { status: "running", progress: "Asking the AI provider to map 66 classes onto 68 table(s)" }, { status: "succeeded", progress: "Done", result: { classes: 66, relations: 40 } }]; return new Response(JSON.stringify({ id: "job-1", kind: "suggest-mapping", version_id: vid, ...stages[Math.min(polls - 1, 2)], started_at: "2026-09-21T10:00:00Z", progress_at: "2026-09-21T10:00:05Z", finished_at: polls >= 3 ? "2026-09-21T10:02:00Z" : null, error: null })); }
      if (key === "GET /api/jobs/job-2") return new Response(JSON.stringify({ id: "job-2", kind: "draft-ontology", version_id: vid, status: "failed", progress: "Asking the AI provider", started_at: "2026-09-21T10:00:00Z", progress_at: "2026-09-21T10:00:05Z", finished_at: "2026-09-21T10:01:00Z", result: null, error: "LLMOutputError: the model returned no JSON" }));
      if (key === `POST /api/versions/${vid}/llm/draft-ontology?background=true`) return new Response(JSON.stringify({ id: "job-2", kind: "draft-ontology", version_id: vid, status: "running", progress: "Queued" }), { status: 202 });
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const a = new RestApi({ base: "/api", pollMs: 1 }); await a.domain("aw");
    const seen: string[] = [];
    const r = await a.suggestMapping("aw", 1, p => seen.push(p.progress));
    expect(r).toEqual({ classes: 66, relations: 40, skipped: [] });
    expect(seen).toEqual(["Queued", "Describing table 3 of 68: customer", "Asking the AI provider to map 66 classes onto 68 table(s)"]);
    await expect(a.draftOntology("aw", 1, { ai: true }, () => {})).rejects.toThrow(/returned no JSON/);
  });
  it("rest: picks up a suggestion already running for the version and follows it to the end", async () => {
    const vid = "eeeeeeee-0000-0000-0000-000000000002"; let polls = 0;
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`;
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/aw": { name: "aw", description: "", base_iri: "http://p/aw/", review_quorum: 1, materialization: "none", sources: [] },
        "GET /api/domains/aw/versions/summary": [{ id: vid, version: 1, status: "draft", has_ontology: true, has_mapping: false, rule_count: 0, constraint_count: 0, created_at: "2026-09-21T10:00:00Z", created_by: "alice", is_active: false, stats: { classes: 2, attributes: 2, relationships: 1, bindings: 0, rules: 0, constraints: 0, triples: 0 }, mapping: null, last_build: null, review: null, lease: null }],
        "GET /api/domains/cards": [{ name: "aw", version_count: 1, active_version: null, latest_version: { version: 1, status: "draft" }, triples: 0, last_build: null, source: { kind: "databricks", connection: null, catalog: null, schema: null, schemas: [] }, source_count: 0, mcp: { exposed: true, disabled_tools: [] } }],
        [`GET /api/versions/${vid}/jobs?kind=suggest-mapping`]: { id: "job-9", kind: "suggest-mapping", version_id: vid, status: "running", progress: "Describing table 40 of 68: product", started_at: "2026-09-21T10:00:00Z", progress_at: "2026-09-21T10:01:40Z", finished_at: null, result: null, error: null },
      };
      if (key === "GET /api/jobs/job-9") { polls++; return new Response(JSON.stringify({ id: "job-9", kind: "suggest-mapping", version_id: vid, status: polls >= 2 ? "succeeded" : "running", progress: polls >= 2 ? "Done" : "Asking the AI provider to map 66 classes onto 68 table(s)", started_at: "2026-09-21T10:00:00Z", progress_at: "2026-09-21T10:03:00Z", finished_at: polls >= 2 ? "2026-09-21T10:05:00Z" : null, result: polls >= 2 ? { classes: 66, relations: 40 } : null, error: null })); }
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const a = new RestApi({ base: "/api", pollMs: 1 }); await a.domain("aw");
    const seen: string[] = [];
    const end = await a.runningAiJob("aw", 1, "suggest-mapping", p => seen.push(p.progress));
    expect(seen[0]).toBe("Describing table 40 of 68: product");
    expect(seen).toContain("Asking the AI provider to map 66 classes onto 68 table(s)");
    expect(end).toMatchObject({ status: "succeeded" });
    expect(await new MockApi().runningAiJob("rgm", 3, "suggest-mapping")).toBeNull();
  });
  it("mock: reports a couple of stages too", async () => {
    const api = new MockApi({ latency: 0 });
    const seen: string[] = [];
    await api.suggestMapping("rgm", 3, p => seen.push(p.progress));
    expect(seen.length).toBeGreaterThan(0);
  });
});


describe("Explore search filters and neighbour names", () => {
  it("rest: passes the type and match to the search, lists types with counts and names neighbours", async () => {
    const vid = "ffffffff-0000-0000-0000-000000000001"; const calls: string[] = [];
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url}`; calls.push(key);
      const routes: Record<string, unknown> = {
        "GET /api/auth/config": { mode: "header", header: "X-Actor", source: { kind: "databricks", catalog: "finops_metadata" } },
        "GET /api/domains/aw": { name: "aw", description: "", base_iri: "http://p/aw/", review_quorum: 1, materialization: "none", sources: [] },
        "GET /api/domains/aw/versions/summary": [{ id: vid, version: 1, status: "published", has_ontology: true, has_mapping: true, rule_count: 0, constraint_count: 0, created_at: "2026-09-21T10:00:00Z", created_by: "alice", is_active: true, stats: { classes: 2, attributes: 2, relationships: 1, bindings: 0, rules: 0, constraints: 0, triples: 10 }, mapping: null, last_build: null, review: null, lease: null }],
        "GET /api/domains/cards": [{ name: "aw", version_count: 1, active_version: { version: 1 }, latest_version: { version: 1, status: "published" }, triples: 10, last_build: null, source: { kind: "databricks", connection: null, catalog: null, schema: null, schemas: [] }, source_count: 0, mcp: { exposed: true, disabled_tools: [] } }],
        [`GET /api/versions/${vid}/graph/status`]: { triples: 10, inferred: 0, types: { "http://p/aw#Customer": 7, "http://p/aw#SalesOrder": 3 } },
        [`GET /api/versions/${vid}/graph/overview?limit=300`]: { nodes: [{ iri: "http://p/aw/Customer/1", label: "Ann", types: ["http://p/aw#Customer"] }, { iri: "http://p/aw/SalesOrder/9", label: "", types: [] }], edges: [{ source: "http://p/aw/Customer/1", predicate: "http://p/aw#placesOrder", target: "http://p/aw/SalesOrder/9" }] },
        [`GET /api/versions/${vid}/graph/search?q=ann&limit=20&match=starts_with&type=${encodeURIComponent("http://p/aw#Customer")}`]: [{ iri: "http://p/aw/Customer/1", label: "Ann", types: ["http://p/aw#Customer"] }],
        [`GET /api/versions/${vid}/graph/entity?iri=${encodeURIComponent("http://p/aw/Customer/1")}`]: { iri: "http://p/aw/Customer/1", label: "Ann", types: ["http://p/aw#Customer"], attributes: [], outgoing: [{ predicate: "http://p/aw#placesOrder", target: "http://p/aw/SalesOrder/9", inferred: false }], incoming: [], neighbours: [{ iri: "http://p/aw/SalesOrder/9", label: "Order 9", types: ["http://p/aw#SalesOrder"] }] },
      };
      return new Response(JSON.stringify(routes[key] ?? { detail: `no route ${key}` }), { status: key in routes ? 200 : 404 });
    }) as typeof fetch;
    const a = new RestApi({ base: "/api" }); await a.domain("aw");
    const st = await a.graphStatus("aw");
    expect(st.types).toEqual([{ name: "Customer", iri: "http://p/aw#Customer", count: 7 }, { name: "SalesOrder", iri: "http://p/aw#SalesOrder", count: 3 }]);
    expect(st.entities).toBe("10");
    expect(await a.graphOverview("aw")).toEqual({ nodes: [{ id: "http://p/aw/Customer/1", label: "Ann", type: "Customer" }, { id: "http://p/aw/SalesOrder/9", label: "9", type: "" }], edges: [{ from: "http://p/aw/Customer/1", to: "http://p/aw/SalesOrder/9", label: "placesOrder" }] });
    expect(await a.search("aw", "ann", { type: "http://p/aw#Customer", match: "starts_with" })).toEqual([{ id: "http://p/aw/Customer/1", label: "Ann", type: "Customer" }]);
    const e = await a.entity("aw", "http://p/aw/Customer/1");
    expect(e.out[0].targets[0]).toEqual({ id: "http://p/aw/SalesOrder/9", label: "Order 9", type: "SalesOrder" });   // named, not "9"
  });
  it("mock: filters by type and match", async () => {
    const api = new MockApi();
    const all = await api.search("rgm", "");
    const customers = await api.search("rgm", "", { type: "http://polestar.ai/rgm#Customer" });
    expect(customers.length).toBeGreaterThan(0); expect(customers.length).toBeLessThan(all.length); expect(customers.every(h => h.type === "Customer")).toBe(true);
    expect((await api.graphStatus("rgm")).types.map(t => t.name)).toContain("Customer");
  });
});
