// Design data for the mock adapter (rgm / hr / finops as drawn in the Datagraph UI design).
import type { Analytics, ApiKey, Constraint, DomainSummary, EntityDetail, GlossaryTerm, Lock, OntoClass, OntoCheck, OntoDiff, Principal, Rule, Task } from "./types";
import type { ClassMapping, TablePreview } from "./types";

const BASE = "http://polestar.ai/rgm";

export const CLASSES: OntoClass[] = [
  { id: "Category", x: 10, y: 20, desc: "Top-level product taxonomy used in RGM planning.", parents: [], attrs: [["categoryName", "xsd:string"], ["categoryCode", "xsd:string"]], rels: [] },
  { id: "Brand", x: 28, y: 33, desc: "Owned or competitor brand.", parents: [], attrs: [["brandName", "xsd:string"], ["owner", "xsd:string"], ["tier", "xsd:string"]], rels: [["inCategory", "Category"]] },
  { id: "Product", x: 46, y: 20, desc: "A sellable SKU with pack size and list price.", parents: [], attrs: [["sku", "xsd:string"], ["productName", "xsd:string"], ["packSize", "xsd:decimal"], ["listPrice", "xsd:decimal"]], rels: [["hasBrand", "Brand"]] },
  { id: "Promotion", x: 66, y: 10, desc: "A priced promotion window for one or more products.", parents: [], attrs: [["promoName", "xsd:string"], ["startDate", "xsd:date"], ["endDate", "xsd:date"], ["mechanic", "xsd:string"]], rels: [["promotes", "Product"]] },
  { id: "Sale", x: 52, y: 55, desc: "One transaction line: product sold to a customer at a store.", parents: [], attrs: [["saleDate", "xsd:date"], ["quantity", "xsd:integer"], ["grossRevenue", "xsd:decimal"], ["netRevenue", "xsd:decimal"], ["discount", "xsd:decimal"]], rels: [["ofProduct", "Product"], ["soldTo", "Customer"], ["atStore", "Store"], ["viaChannel", "Channel"]] },
  { id: "Customer", x: 22, y: 68, desc: "A trade customer: retailer, wholesaler or distributor.", parents: [], attrs: [["customerName", "xsd:string"], ["segment", "xsd:string"], ["country", "xsd:string"], ["since", "xsd:date"]], rels: [] },
  { id: "KeyAccount", x: 8, y: 88, desc: "A customer managed by a national account team.", parents: ["Customer"], attrs: [["accountManager", "xsd:string"], ["contractEnd", "xsd:date"]], rels: [] },
  { id: "Store", x: 78, y: 48, desc: "A physical or online point of sale.", parents: [], attrs: [["storeName", "xsd:string"], ["format", "xsd:string"], ["sqm", "xsd:integer"]], rels: [["inRegion", "Region"]] },
  { id: "Region", x: 92, y: 28, desc: "Sales region.", parents: [], attrs: [["regionName", "xsd:string"], ["countryIso", "xsd:string"]], rels: [] },
  { id: "Channel", x: 84, y: 80, desc: "Route to market.", parents: [], attrs: [["channelName", "xsd:string"]], rels: [] },
  { id: "Invoice", x: 40, y: 88, desc: "A billed document for one or more sales.", parents: [], attrs: [["invoiceNo", "xsd:string"], ["issuedAt", "xsd:date"], ["total", "xsd:decimal"]], rels: [["bills", "Sale"]] },
  { id: "Shipment", x: 64, y: 90, desc: "Physical fulfilment of an invoice.", parents: [], attrs: [["shippedAt", "xsd:date"], ["carrier", "xsd:string"]], rels: [["fulfils", "Invoice"]] },
].map(c => ({ ...c, iri: `${BASE}#${c.id}`, attrs: c.attrs.map(([name, range]) => ({ name, range })), rels: c.rels.map(([name, target]) => ({ name, target })) }));

export const MAP: Record<string, ClassMapping> = {
  Customer: { table: ["gold", "dim_customer"], key: "customer_id", state: "complete", cols: { customerName: "customer_name", segment: "segment_code", country: "country_iso", since: "onboarded_at" } },
  Product: { table: ["gold", "dim_product"], key: "product_id", state: "complete", cols: { sku: "sku", productName: "product_name", packSize: "pack_size", listPrice: "list_price" }, rels: { hasBrand: "FK brand_id" } },
  Sale: { table: ["gold", "fct_sales"], key: "sale_id", state: "partial", cols: { saleDate: "sale_date", quantity: "qty", grossRevenue: "gross_rev" }, rels: { ofProduct: "FK product_id", soldTo: "FK customer_id", atStore: "FK store_id" } },
  Store: { table: ["gold", "dim_store"], key: "store_id", state: "complete", cols: { storeName: "store_name", format: "format_code", sqm: "floor_sqm" }, rels: { inRegion: "FK region_id" } },
  Region: { table: ["gold", "dim_region"], key: "region_id", state: "complete", cols: { regionName: "region_name", countryIso: "country_iso" } },
  Brand: { table: ["gold", "dim_brand"], key: "brand_id", state: "partial", cols: { brandName: "brand_name", owner: "owner_name" }, rels: { inCategory: "FK category_id" } },
  Category: { table: ["gold", "dim_category"], key: "category_id", state: "complete", cols: { categoryName: "category_name", categoryCode: "category_code" } },
  Promotion: { table: ["silver", "promo_calendar"], key: "promo_id", state: "partial", cols: { promoName: "promo_name", startDate: "start_dt", endDate: "end_dt" }, rels: { promotes: "bridge_promo_product (promo_id → product_id)" } },
  Invoice: { table: ["gold", "fct_invoice"], key: "invoice_id", state: "complete", cols: { invoiceNo: "invoice_no", issuedAt: "issued_at", total: "total_amt" }, rels: { bills: "FK sale_id" } },
  KeyAccount: { sql: "SELECT * FROM dim_customer WHERE is_key_account = true", key: "customer_id", state: "partial", cols: { accountManager: "nam_owner" } },
};

export const PREVIEW: Record<string, TablePreview> = {
  Customer: { columns: ["customer_id", "customer_name", "segment_code", "country_iso", "onboarded_at", "credit_limit"], rows: [["C-10482", "Carrefour Hypermarché Lyon Part-Dieu", "MODERN_TRADE", "FR", "2019-03-12", "250000"], ["C-10483", "Auchan Villeneuve-d'Ascq", "MODERN_TRADE", "FR", "2018-11-02", "180000"], ["C-11207", "Metro Cash & Carry Nanterre", "WHOLESALE", "FR", "2020-06-30", "95000"], ["C-11888", "Colruyt Halle", "MODERN_TRADE", "BE", "2017-01-15", "210000"], ["C-12041", "Tesco Extra Watford", "MODERN_TRADE", "GB", "2021-09-08", null]] },
  Sale: { columns: ["sale_id", "sale_date", "qty", "gross_rev", "net_rev", "product_id", "customer_id", "store_id", "channel_id"], rows: [["S-88213", "2026-08-30", "144", "2073.60", "1865.20", "P-2201", "C-10482", "ST-118", "CH-1"], ["S-88214", "2026-08-30", "36", "518.40", "518.40", "P-2210", "C-10482", "ST-118", "CH-1"], ["S-88215", "2026-08-31", "240", "3456.00", "2937.60", "P-2201", "C-11888", "ST-402", "CH-2"], ["S-88216", "2026-08-31", "12", "172.80", "172.80", "P-2305", "C-12041", "ST-511", "CH-1"], ["S-88217", "2026-09-01", "96", "1382.40", "1244.16", "P-2210", "C-11207", "ST-207", "CH-3"]] },
};

export const CATALOG: Record<string, [string, number, boolean][]> = {
  gold: [["dim_customer", 8, true], ["dim_product", 11, true], ["dim_store", 7, true], ["dim_region", 4, true], ["dim_brand", 6, true], ["dim_category", 4, true], ["fct_sales", 14, true], ["fct_invoice", 9, true], ["fct_returns", 8, false], ["dim_date", 12, false]],
  silver: [["promo_calendar", 9, true], ["bridge_promo_product", 3, true], ["price_list_raw", 7, false], ["shipments_raw", 10, false]],
  bronze: [["erp_customers_2026", 23, false], ["pos_ticket_lines", 18, false], ["carrier_events", 9, false]],
};

export const COLUMNS: Record<string, { comment: string; cols: [string, string, string, ("pk" | "fk")?][] }> = {
  dim_customer: { comment: "One row per trade customer, deduplicated from ERP and CRM.", cols: [["customer_id", "BIGINT", "Surrogate key", "pk"], ["customer_name", "STRING", "Legal trading name"], ["segment_code", "STRING", "MODERN_TRADE / WHOLESALE / ECOM"], ["country_iso", "STRING", "ISO 3166-1 alpha-2"], ["onboarded_at", "DATE", "First invoice date"], ["credit_limit", "DECIMAL(12,2)", "Approved credit in EUR"], ["parent_customer_id", "BIGINT", "Group parent, nullable", "fk"], ["is_key_account", "BOOLEAN", "Managed by a NAM"]] },
  fct_sales: { comment: "Transaction lines from POS and EDI, daily grain.", cols: [["sale_id", "BIGINT", "Surrogate key", "pk"], ["sale_date", "DATE", "Transaction date"], ["qty", "INT", "Units"], ["gross_rev", "DECIMAL(14,2)", "Before discounts"], ["net_rev", "DECIMAL(14,2)", "After discounts"], ["product_id", "BIGINT", "→ dim_product", "fk"], ["customer_id", "BIGINT", "→ dim_customer", "fk"], ["store_id", "BIGINT", "→ dim_store", "fk"], ["channel_id", "BIGINT", "→ dim_channel (missing)", "fk"]] },
};
export const GENERIC_COLS = { comment: "Table comment not set in the catalog.", cols: [["id", "BIGINT", "Surrogate key", "pk"], ["name", "STRING", ""], ["code", "STRING", ""], ["updated_at", "TIMESTAMP", "Last ETL write"]] as [string, string, string, ("pk" | "fk")?][] };

export const PROFILE: Record<string, { rows: string; fresh: string; dup: string; cols: Record<string, [number, number]> }> = {
  dim_customer: { rows: "612", fresh: "today 04:10", dup: "0", cols: { customer_id: [0, 612], customer_name: [0, 611], segment_code: [0, 3], country_iso: [0.5, 6], onboarded_at: [2.1, 402], credit_limit: [18.4, 77], parent_customer_id: [61.2, 38], is_key_account: [0, 2] } },
  fct_sales: { rows: "9,840,112", fresh: "today 05:02", dup: "14", cols: { sale_id: [0, 9840112], sale_date: [0, 731], qty: [0, 412], gross_rev: [0, 88120], net_rev: [0.2, 90211], product_id: [0, 388], customer_id: [0, 612], store_id: [0, 301], channel_id: [37.9, 4] } },
};
export const DQ_BY_COL: Record<string, [string, string]> = { qty: ["12 violations", "min_exclusive"], country_iso: ["3 warnings", "pattern"], channel_id: ["no target", "drift"], parent_customer_id: ["no check", "—"] };
export const TERM_BY_COL: Record<string, string> = { customer_name: "Trade customer", segment_code: "Segment", credit_limit: "Credit limit", net_rev: "Net revenue", gross_rev: "Gross revenue", qty: "Units", is_key_account: "Key account", channel_id: "Route to market" };
export const GLOSSARY: GlossaryTerm[] = [
  { term: "Trade customer", def: "A legal entity that buys from us for resale: retailer, wholesaler or distributor. Not the end consumer.", cls: "Customer", cols: ["dim_customer.customer_name"], steward: "priya" },
  { term: "Key account", def: "A trade customer managed by a national account manager under a framework contract.", cls: "KeyAccount", cols: ["dim_customer.is_key_account"], steward: "priya" },
  { term: "Net revenue", def: "Gross revenue minus on-invoice and off-invoice discounts, before returns.", cls: "Sale", cols: ["fct_sales.net_rev"], steward: "marc" },
  { term: "Gross revenue", def: "Units × list price at the time of sale.", cls: "Sale", cols: ["fct_sales.gross_rev"], steward: "marc" },
  { term: "Segment", def: "Commercial grouping of customers: MODERN_TRADE, WHOLESALE, ECOM.", cls: "Customer", cols: ["dim_customer.segment_code"], steward: "priya" },
  { term: "Credit limit", def: "Approved outstanding exposure in EUR, set by finance.", cls: "Customer", cols: ["dim_customer.credit_limit"], steward: "lena" },
  { term: "Route to market", def: "How the product reaches the point of sale: direct, distributor, e-commerce.", cls: "Channel", cols: ["fct_sales.channel_id"], steward: "marc" },
  { term: "Units", def: "Consumer units sold, not cases.", cls: "Sale", cols: ["fct_sales.qty"], steward: "marc" },
];
export const TABLE_CLASS: Record<string, string> = { dim_customer: "Customer", dim_product: "Product", dim_store: "Store", dim_region: "Region", dim_brand: "Brand", dim_category: "Category", fct_sales: "Sale", fct_invoice: "Invoice", promo_calendar: "Promotion" };
export const ONTO_DIFFS: Record<string, OntoDiff[]> = {
  dim_customer: [{ kind: "new column", column: "credit_limit", note: "not in Customer", action: "Add as attribute" }, { kind: "new column", column: "parent_customer_id", note: "FK → dim_customer, no relationship", action: "Add as relationship" }, { kind: "new column", column: "is_key_account", note: "flag; KeyAccount subclass already exists", action: "Add as restriction" }],
  fct_sales: [{ kind: "new column", column: "net_rev", note: "Sale.netRevenue exists but is unbound", action: "Bind in Mapping" }, { kind: "missing target", column: "channel_id", note: "Channel has no table (drift)", action: "Open in Mapping" }],
};

const changes = (xs: [string, string][]) => xs.map(([sign, text]) => ({ sign: sign as "+" | "-" | "~", text }));
const review = (approved: number, quorum: number, rows: [string, string, "approved" | "pending"][]) => ({ approved, quorum, rows: rows.map(([who, note, state]) => ({ who, note, state })) });

export const DOMAINS: DomainSummary[] = [
  {
    name: "rgm", description: "Revenue growth management", base_iri: "http://polestar.ai/rgm/", quorum: 3, schema: "gold", schemas: ["gold", "silver"], sources: [{ connectionId: "c-warehouse", catalog: "rgm", schemas: ["gold", "silver"] }], catalog: "rgm", materialization: "view · Liquid Clustering", target: "finops_metadata.rgm_graph", mcpExposed: true, disabledTools: ["run_action", "materialize_cohort"], triples: "263,695", lastBuild: "2 h ago",
    versions: [
      { version: 3, status: "draft", content: "ontology · mapping 78% · 2 rules · 7 constraints", mappingPct: 78, lastBuild: "succeeded · 2 h ago", active: false, created: "3 d ago", by: "alice", stats: { classes: 12, attrs: 52, rels: 11, bindings: 41, rules: 2, constraints: 7, triples: 263695 }, lease: { holder: "alice", expires: "42 min" }, changes: changes([["+", "class KeyAccount ⊂ Customer"], ["+", "Promotion, Shipment classes and 5 attributes"], ["~", "Sale.netRevenue unbound after fct_sales change"], ["+", "constraint Every entity is labelled (info)"]]) },
      { version: 2, status: "in_review", content: "ontology · mapping 100% · 2 rules · 6 constraints", mappingPct: 100, lastBuild: "succeeded · 5 d ago", active: false, created: "9 d ago", by: "marc", stats: { classes: 10, attrs: 47, rels: 9, bindings: 47, rules: 2, constraints: 6, triples: 258102 }, review: review(2, 3, [["priya", "reviewed mapping", "approved"], ["marc", "checked the Sale class", "approved"], ["lena", "", "pending"]]), changes: changes([["+", "rule Discount above list price (violation)"], ["+", "Invoice → Sale relationship bills"], ["~", "Store.format widened to STRING"]]) },
      { version: 1, status: "published", content: "ontology · mapping 100% · 1 rule · 5 constraints", mappingPct: 100, lastBuild: "succeeded · 12 d ago", active: true, created: "31 d ago", by: "alice", stats: { classes: 9, attrs: 44, rels: 8, bindings: 44, rules: 1, constraints: 5, triples: 241880 }, changes: changes([["+", "initial ontology drafted from 14 gold tables"], ["+", "rule Customer bought product"]]) },
    ],
    lease: { holder: "alice", expires: "42 min" }, review: review(2, 3, [["priya", "reviewed mapping", "approved"], ["marc", "checked the Sale class", "approved"], ["lena", "", "pending"]]),
  },
  {
    name: "hr", description: "People and departments", base_iri: "http://polestar.ai/hr/", quorum: 1, schema: "people", schemas: ["people"], sources: [{ connectionId: "c-warehouse", catalog: "hr", schemas: ["people"] }], catalog: "hr", materialization: "table · OPTIMIZE nightly", target: "finops_metadata.hr_graph", mcpExposed: true, disabledTools: [], triples: "41,880", lastBuild: "3 d ago",
    versions: [
      { version: 3, status: "published", content: "ontology · mapping 100% · 1 rule · 4 constraints", mappingPct: 100, lastBuild: "succeeded · 3 d ago", active: true, created: "8 d ago", by: "lena", stats: { classes: 6, attrs: 28, rels: 5, bindings: 28, rules: 1, constraints: 4, triples: 41880 }, changes: changes([["+", "class Position"], ["+", "constraint Employee has a manager"]]) },
      { version: 2, status: "archived", content: "ontology · mapping 100%", mappingPct: 100, lastBuild: "succeeded · 40 d ago", active: false, created: "45 d ago", by: "lena", stats: { classes: 5, attrs: 24, rels: 4, bindings: 24, rules: 0, constraints: 3, triples: 39012 }, changes: changes([["+", "Location class"]]) },
      { version: 1, status: "archived", content: "ontology · mapping 100%", mappingPct: 100, lastBuild: "succeeded · 90 d ago", active: false, created: "95 d ago", by: "lena", stats: { classes: 4, attrs: 20, rels: 3, bindings: 20, rules: 0, constraints: 3, triples: 36400 }, changes: changes([["+", "initial Employee, Department, Manager draft"]]) },
    ],
    lease: null, review: review(1, 1, [["lena", "approved v3", "approved"]]),
  },
  { name: "finops", description: "Cloud cost allocation", base_iri: "http://polestar.ai/finops/", quorum: 2, schema: "billing", schemas: ["billing"], sources: [{ connectionId: null, catalog: "finops_metadata", schemas: ["billing"] }], catalog: "finops_metadata", materialization: "view", target: "finops_metadata.finops_graph", mcpExposed: false, disabledTools: [], triples: "—", lastBuild: "never", versions: [], lease: null, review: null },
];

export const AUDIT: Record<string, [string, string, number, string][]> = {
  rgm: [["alice", "took the lease on", 3, "42 min ago"], ["marc", "submitted for review", 2, "5 d ago"], ["priya", "approved", 2, "4 d ago"], ["marc", "approved", 2, "4 d ago"], ["alice", "created draft from v1", 3, "3 d ago"], ["alice", "set active version", 1, "12 d ago"], ["lena", "published", 1, "12 d ago"]],
  hr: [["lena", "published", 3, "3 d ago"], ["lena", "set active version", 3, "3 d ago"], ["lena", "archived", 2, "3 d ago"]],
  finops: [["alice", "created domain", 0, "1 d ago"]],
};
export const COMMENTS: Record<string, [string, string, string][]> = {
  rgm: [["marc", "yesterday", "Channel is still unmapped; do we have dim_channel in gold yet?"], ["alice", "2 h ago", "Not yet. Added it to the drift list, build keeps the v1 graph meanwhile."]],
  hr: [["lena", "3 d ago", "Published v3 with the new Position class."]], finops: [],
};

export const ENTITIES: Record<string, EntityDetail> = {
  "C-10482": { id: "C-10482", label: "Carrefour Hypermarché Lyon Part-Dieu", type: "Customer", iri: `${BASE}/Customer/C-10482`, attrs: [["customerName", "Carrefour Hypermarché Lyon Part-Dieu", "string"], ["segment", "MODERN_TRADE", "string"], ["country", "FR", "string"], ["since", "2019-03-12", "date"], ["creditLimit", "250 000", "decimal"], ["tier", "Tier 1", "", true]].map(([k, v, dt, inf]) => ({ k: k as string, v: v as string, dt: dt ? `xsd:${dt}` : "", inferred: !!inf })), out: [{ pred: "parentCustomer", targets: [{ id: "C-10001", label: "Carrefour France", type: "Customer" }] }], inc: [{ pred: "soldTo", count: "3,412 sales", targets: [{ id: "S-88213", label: "Sale S-88213", type: "Sale" }, { id: "S-88214", label: "Sale S-88214", type: "Sale" }, { id: "S-87990", label: "Sale S-87990", type: "Sale" }] }], far: [{ pred: "hasBrand", target: { id: "B-12", label: "Sparkle", type: "Brand" } }, { pred: "inRegion", target: { id: "R-AURA", label: "Auvergne-Rhône-Alpes", type: "Region" } }, { pred: "bills", target: { id: "INV-5510", label: "Invoice INV-5510", type: "Invoice" } }] },
  "C-10001": { id: "C-10001", label: "Carrefour France", type: "KeyAccount", iri: `${BASE}/Customer/C-10001`, attrs: [{ k: "customerName", v: "Carrefour France", dt: "xsd:string", inferred: false }, { k: "accountManager", v: "M. Duval", dt: "xsd:string", inferred: false }, { k: "contractEnd", v: "2027-12-31", dt: "xsd:date", inferred: false }, { k: "type", v: "Customer", dt: "", inferred: true }], out: [], inc: [{ pred: "parentCustomer", count: "212 customers", targets: [{ id: "C-10482", label: "Carrefour Hypermarché Lyon Part-Dieu", type: "Customer" }, { id: "C-10490", label: "Carrefour Market Bron", type: "Customer" }] }], far: [] },
  "S-88213": { id: "S-88213", label: "Sale S-88213", type: "Sale", iri: `${BASE}/Sale/S-88213`, attrs: [{ k: "saleDate", v: "2026-08-30", dt: "xsd:date", inferred: false }, { k: "quantity", v: "144", dt: "xsd:integer", inferred: false }, { k: "grossRevenue", v: "2 073.60", dt: "xsd:decimal", inferred: false }, { k: "netRevenue", v: "1 865.20", dt: "xsd:decimal", inferred: false }], out: [{ pred: "soldTo", targets: [{ id: "C-10482", label: "Carrefour Hypermarché Lyon Part-Dieu", type: "Customer" }] }, { pred: "ofProduct", targets: [{ id: "P-2201", label: "Sparkle Cola 1.5L ×6", type: "Product" }] }, { pred: "atStore", targets: [{ id: "ST-118", label: "Lyon Part-Dieu", type: "Store" }] }], inc: [{ pred: "bills", count: "1 invoice", targets: [{ id: "INV-5510", label: "Invoice INV-5510", type: "Invoice" }] }], far: [] },
  "P-2201": { id: "P-2201", label: "Sparkle Cola 1.5L ×6", type: "Product", iri: `${BASE}/Product/P-2201`, attrs: [{ k: "sku", v: "SPC-15-6", dt: "xsd:string", inferred: false }, { k: "packSize", v: "6", dt: "xsd:decimal", inferred: false }, { k: "listPrice", v: "14.40", dt: "xsd:decimal", inferred: false }], out: [{ pred: "hasBrand", targets: [{ id: "B-12", label: "Sparkle", type: "Brand" }] }], inc: [{ pred: "ofProduct", count: "41,208 sales", targets: [{ id: "S-88213", label: "Sale S-88213", type: "Sale" }, { id: "S-88215", label: "Sale S-88215", type: "Sale" }] }, { pred: "promotes", count: "6 promotions", targets: [{ id: "PR-31", label: "Summer 2026 BOGOF", type: "Promotion" }] }], far: [] },
};
export const SEARCH = [["C-10482", "Carrefour Hypermarché Lyon Part-Dieu", "Customer"], ["C-10001", "Carrefour France", "KeyAccount"], ["P-2201", "Sparkle Cola 1.5L ×6", "Product"], ["S-88213", "Sale S-88213", "Sale"], ["ST-118", "Lyon Part-Dieu", "Store"]].map(([id, label, type]) => ({ id, label, type }));

// [subject, predicate, object, objectIsIri, inferred, datatype]
export const TRIPLES: [string, string, string, number, number, string?][] = [
  ["Customer/C-10482", "rdf:type", "rgm:Customer", 1, 0], ["Customer/C-10482", "rgm:customerName", "Carrefour Hypermarché Lyon Part-Dieu", 0, 0, "xsd:string"], ["Customer/C-10482", "rgm:segment", "MODERN_TRADE", 0, 0, "xsd:string"], ["Customer/C-10482", "rgm:country", "FR", 0, 0, "xsd:string"], ["Customer/C-10482", "rgm:tier", "Tier 1", 0, 1, "xsd:string"], ["Sale/S-88213", "rgm:soldTo", "Customer/C-10482", 1, 0], ["Sale/S-88213", "rgm:ofProduct", "Product/P-2201", 1, 0], ["Sale/S-88213", "rgm:netRevenue", "1865.20", 0, 0, "xsd:decimal"], ["Customer/C-10482", "rgm:boughtProduct", "Product/P-2201", 1, 1], ["Product/P-2201", "rgm:hasBrand", "Brand/B-12", 1, 0], ["Product/P-2201", "rgm:inCategory", "Category/CAT-4", 1, 1], ["Store/ST-118", "rgm:inRegion", "Region/R-AURA", 1, 0], ["Invoice/INV-5510", "rgm:bills", "Sale/S-88213", 1, 0], ["Customer/C-10001", "rdf:type", "rgm:Customer", 1, 1],
];

export const STEP_NAMES: [string, string][] = [["compile", "57 selects"], ["load", "263,695 rows"], ["infer", "OWL RL closure"], ["rules", "2 rules"], ["quality", "7 constraints"], ["publish", "warehouse views"]];
export const STEP_SECS = [0.41, 38.2, 12.7, 3.1, 4.8, 2.2];

export const RULES: Rule[] = [
  { name: "Customer bought product", mode: "materialize", text: "Sale(?s) ^ soldTo(?s,?c) ^ ofProduct(?s,?p) → boughtProduct(?c,?p)", enabled: true, lastRun: "2 h ago · +19,204 triples" },
  { name: "Discount above list price", mode: "violation", text: "Sale(?s) ^ discount(?s,?d) ^ grossRevenue(?s,?g) ^ swrlb:greaterThan(?d,?g) → Violation(?s)", enabled: true, lastRun: "2 h ago · 0 violations" },
];
export const CONSTRAINTS: Constraint[] = [
  { name: "Customer has a name", target: "Customer", kind: "min_count", severity: "violation", count: 0, sample: "—" },
  { name: "Sale quantity is positive", target: "Sale", kind: "min_exclusive", severity: "violation", count: 12, sample: "Sale/S-71002 …", sampleEntity: "S-88213" },
  { name: "Country is ISO-2", target: "Customer", kind: "pattern", severity: "warning", count: 3, sample: "Customer/C-11207 …", sampleEntity: "C-10482" },
  { name: "Product has one brand", target: "Product", kind: "max_count", severity: "violation", count: 0, sample: "—" },
  { name: "Every entity is labelled", target: "*", kind: "require_label", severity: "info", count: 312, sample: "Shipment/SH-1 …" },
];
export const CHECKS: OntoCheck[] = [
  { severity: "warning", code: "no_range", subject: "viaChannel", message: "Object property has a range (Channel) but Channel has no attributes.", target: { screen: "ontology", cls: "Channel" } },
  { severity: "info", code: "unused_class", subject: "Shipment", message: "No instances expected: class is not mapped to any table.", target: { screen: "mapping", cls: "Shipment" } },
];
export const ANALYTICS: Analytics = {
  health: [{ label: "Triples", value: "263,695", sub: "+23,207 inferred", tone: "blue" }, { label: "Entities", value: "12,445", sub: "12 classes", tone: "ink" }, { label: "Edges", value: "109k", sub: "10 predicates", tone: "ink" }, { label: "Orphans", value: "312", sub: "no label or link", tone: "warn" }],
  perClass: [{ label: "Sale", n: 9840, color: "#2249FF" }, { label: "Invoice", n: 1210, color: "#4D68FF" }, { label: "Customer", n: 612, color: "#0F27A8" }, { label: "Product", n: 388, color: "#8FA1FF" }, { label: "Store", n: 301, color: "#D4DCFF" }, { label: "Promotion", n: 94, color: "#D4DCFF" }],
  runs: [{ kind: "Communities · Louvain", params: "res 1.0 · seed 42", result: "14 communities", when: "2 h ago" }, { kind: "Betweenness", params: "top 50", result: "50 nodes", when: "2 h ago" }, { kind: "PageRank", params: "top 50", result: "50 nodes", when: "12 d ago" }],
  top: [{ label: "Carrefour France", type: "KeyAccount", score: "0.412", entity: "C-10001" }, { label: "Sparkle Cola 1.5L ×6", type: "Product", score: "0.288", entity: "P-2201" }, { label: "Lyon Part-Dieu", type: "Store", score: "0.131", entity: "C-10482" }, { label: "Carrefour Hypermarché Lyon Part-Dieu", type: "Customer", score: "0.097", entity: "C-10482" }],
};
export const TASKS: Task[] = [
  { title: "Review rgm v2", sub: "Submitted by marc · 2 of 3 approvals", when: "5 d", icon: "tasks", go: { screen: "versions", domain: "rgm", version: 2 } },
  { title: "Your lease on rgm v3 expires soon", sub: "42 minutes left · release or renew", when: "now", icon: "settings", go: { screen: "overview", domain: "rgm", version: 3 } },
  { title: "Build #9e02 failed on hr v4", sub: "compile: relation viaChannel on Sale has no target key", when: "3 d", icon: "build", go: { screen: "build", domain: "hr" } },
];
export const PRINCIPALS: Principal[] = [{ name: "alice", role: "admin", seen: "now" }, { name: "priya", role: "reviewer", seen: "1 h ago" }, { name: "marc", role: "builder", seen: "yesterday" }, { name: "svc-databricks-app", role: "viewer", seen: "2 min ago" }];
export const API_KEYS: ApiKey[] = [{ name: "Insight Portal agent", prefix: "of_3k9…", role: "viewer" }, { name: "CI builder", prefix: "of_q1x…", role: "builder" }];
export const LOCKS: Lock[] = [{ what: "rgm v3", who: "alice", exp: "42 min" }, { what: "hr v4", who: "marc", exp: "12 min" }];

import type { ConnectorSpec, ConnectionRec } from "./types";
const F = (name: string, label: string, kind: "text" | "password" | "number" | "select" = "text", required = true, def: string | number | null = null, options: string[] = [], help: string | null = null) => ({ name, label, kind, required, default: def, options, help });
export const CONNECTOR_SPECS: ConnectorSpec[] = [
  { kind: "postgres", label: "PostgreSQL", category: "source", secret_field: "password", docs: "https://www.postgresql.org/docs/current/libpq-connect.html", fields: [F("host", "Host"), F("port", "Port", "number", true, 5432), F("database", "Database"), F("user", "User"), F("password", "Password", "password", false), F("schema", "Default schema", "text", false, "public", [], "Schema the catalog browser opens on"), F("sslmode", "SSL mode", "select", false, "prefer", ["disable", "prefer", "require"])] },
  { kind: "databricks", label: "Databricks SQL warehouse", category: "source", secret_field: "token", docs: "https://docs.databricks.com/dev-tools/python-sql-connector.html", fields: [F("host", "Workspace host", "text", true, null, [], "adb-<id>.<n>.azuredatabricks.net, without https://"), F("http_path", "HTTP path", "text", true, null, [], "/sql/1.0/warehouses/<warehouse id>"), F("token", "Access token", "password", false), F("catalog", "Catalog", "text", false, null, [], "Unity Catalog name used as the session default"), F("schema", "Default schema", "text", false)] },
  { kind: "sqlserver", label: "SQL Server", category: "source", secret_field: "password", docs: "https://learn.microsoft.com/sql/connect/python/python-driver-for-sql-server", fields: [F("host", "Host"), F("port", "Port", "number", true, 1433), F("database", "Database"), F("user", "User"), F("password", "Password", "password", false), F("schema", "Default schema", "text", false, "dbo"), F("driver", "Driver", "select", false, "auto", ["auto", "pyodbc", "pymssql"]), F("encrypt", "Encrypt", "select", false, "yes", ["yes", "no"])] },
  { kind: "azure_openai", label: "Azure OpenAI", category: "ai", secret_field: "api_key", docs: "https://learn.microsoft.com/azure/ai-services/openai/reference", fields: [F("endpoint", "Endpoint", "text", true, null, [], "https://<resource>.openai.azure.com"), F("api_key", "API key", "password", false), F("deployment", "Deployment", "text", true, null, [], "Chat deployment name, e.g. gpt-5.1"), F("api_version", "API version", "text", false, "2024-08-01-preview")] },
];
export const CONNECTIONS = (kind: "databricks" | "postgres"): ConnectionRec[] => [
  kind === "databricks"
    ? { id: "c-warehouse", name: "warehouse", kind: "databricks", config: { host: "adb-7405604451793801.1.azuredatabricks.net", http_path: "/sql/1.0/warehouses/8157f8991449cd80", catalog: "finops_metadata" }, has_secret: true, last_test: { ok: true, title: "Connected", detail: "pratham.rana on finops_metadata.default · 17 tables", latency_ms: 1842, at: "2026-09-21T09:12:00Z" }, created_by: "alice", created_at: "2026-09-14T10:00:00Z", updated_at: "2026-09-21T09:12:00Z" }
    : { id: "c-warehouse", name: "warehouse", kind: "postgres", config: { host: "localhost", port: 5439, database: "ontoforge", user: "ontoforge", schema: "public", sslmode: "prefer" }, has_secret: true, last_test: { ok: true, title: "Connected", detail: "PostgreSQL 16.4 · 17 tables in public", latency_ms: 38, at: "2026-09-21T09:12:00Z" }, created_by: "alice", created_at: "2026-09-14T10:00:00Z", updated_at: "2026-09-21T09:12:00Z" },
  { id: "c-lake", name: "lake", kind: "postgres", config: { host: "lake.internal", port: 5432, database: "lake", user: "reader", sslmode: "require" }, has_secret: true, last_test: null, created_by: "marc", created_at: "2026-09-19T10:00:00Z", updated_at: "2026-09-19T10:00:00Z" },
  { id: "c-gpt", name: "gpt-5.1", kind: "azure_openai", config: { endpoint: "https://polestar-openai.openai.azure.com", deployment: "gpt-5.1", api_version: "2024-08-01-preview" }, has_secret: true, last_test: { ok: true, title: "Connected", detail: "42 models available · deployment gpt-5.1", latency_ms: 412, at: "2026-09-20T16:40:00Z" }, created_by: "alice", created_at: "2026-09-15T08:00:00Z", updated_at: "2026-09-20T16:40:00Z" },
];
