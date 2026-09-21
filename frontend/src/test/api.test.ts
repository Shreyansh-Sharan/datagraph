import { describe, expect, it, vi } from "vitest";
import { MockApi } from "@/api/mock";
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
    const d = await api.createDomain({ name: "supply", description: "Supply chain", base_iri: "http://x/supply/", quorum: 2 });
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
    expect(cs.map(c => c.kind)).toEqual(["databricks", "azure_openai"]);
    expect((await new MockApi({ sourceKind: "postgres" }).connections())[0].kind).toBe("postgres");
  });
  it("creates, tests and attaches a connection to a domain", async () => {
    const api = new MockApi({ latency: 0 });
    await expect(api.createConnection({ name: "warehouse", kind: "postgres", config: { host: "h", port: 5432, database: "d", user: "u" } })).rejects.toThrow(/already exists/);
    await expect(api.createConnection({ name: "pg", kind: "postgres", config: { host: "h" } })).rejects.toThrow(/Database is required/);
    const c = await api.createConnection({ name: "pg", kind: "postgres", config: { host: "h", port: 5432, database: "d", user: "u", password: "s3cret" } });
    expect(c.has_secret).toBe(true); expect(c.config).not.toHaveProperty("password");
    expect((await api.testConnectionDraft({ kind: "sqlserver", config: { host: "h" } })).title).toBe("Driver not installed");
    const t = await api.testConnectionById(c.id); expect(t.ok).toBe(true);
    const d = await api.updateDomain("hr", { connection_id: c.id, default_schema: "people", materialization: "table", target_schema: "hr_graph" });
    expect(d.connectionId).toBe(c.id);
    const f = await api.sourceFacts("hr");
    expect(f).toMatchObject({ kind: "postgres", connection: "pg", schema: "people", materialization: "table", target_schema: "hr_graph" });
    await api.deleteConnection(c.id);
    expect((await api.sourceFacts("hr")).connection).toBeNull();
    await expect(api.updateDomain("hr", { materialization: "sideways" as never })).rejects.toThrow(/materialization/);
  });
});
