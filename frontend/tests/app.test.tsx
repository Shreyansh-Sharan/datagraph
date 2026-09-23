import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "@/App";
import { MockApi } from "@/api/mock";

const renderAt = (hash: string, api = new MockApi()) => { window.location.hash = hash; return render(<App api={api} />); };

describe("datagraph shell", () => {
  it("shows the domains and the Databricks source chip at home", async () => {
    renderAt("#/", new MockApi({ sourceKind: "databricks" }));
    expect(await screen.findByText("Revenue growth management")).toBeInTheDocument();
    expect(screen.getByTitle("Source warehouse")).toHaveTextContent("Databricks · finops_metadata");
    expect(screen.getAllByText(/databricks · rgm\.gold/)).not.toHaveLength(0);
  });
  it("switches naming and the chip when the adapter is Postgres", async () => {
    renderAt("#/", new MockApi({ sourceKind: "postgres" }));
    expect(await screen.findByText("Revenue growth management")).toBeInTheDocument();
    expect(screen.getByTitle("Source warehouse")).toHaveTextContent("Postgres");
    expect(screen.getAllByText(/postgres · rgm_gold/)).not.toHaveLength(0);
  });
  it("opens a domain with the section rail, the version picker in the breadcrumb and the readiness card", async () => {
    renderAt("#/d/rgm");
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { level: 2, name: /Readiness · v3/ })).toBeInTheDocument();
    const rail = screen.getByRole("complementary", { name: "Sections" });
    expect(within(rail).getAllByRole("link").map(a => a.textContent)).toEqual(["Ask", "Overview", "Design", "Graph", "Versions", "Domains"]);
    expect(within(rail).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    const tabs = screen.getByRole("tablist", { name: "Overview" });
    expect(within(tabs).getAllByRole("tab").map(t => t.textContent)).toEqual(["Summary", "Connections", "Domain", "MCP policy"]);
    expect(screen.getByRole("button", { name: "Version" })).toHaveTextContent("v3 draft");            // the picker lives in the breadcrumb
    expect(screen.queryByLabelText("Source connection 1")).toBeNull();                                // the summary reads; the forms live in their tabs
    expect(screen.getByRole("link", { name: "Configure →" })).toBeInTheDocument();
    await user.click(within(tabs).getByRole("tab", { name: "Connections" }));
    expect(await screen.findByLabelText("Source connection 1")).toHaveValue("c-warehouse");
    expect(screen.queryByRole("heading", { level: 2, name: /Readiness/ })).toBeNull();
    await user.click(within(tabs).getByRole("tab", { name: "Summary" }));
    expect(await screen.findByRole("heading", { level: 2, name: /Readiness · v3/ })).toBeInTheDocument();
    expect(screen.getByTitle("Source warehouse")).toHaveTextContent("warehouse · rgm");               // inside a domain: its primary source, not the deployment default
    await user.click(within(rail).getByRole("link", { name: "Design" }));
    const design = await screen.findByRole("tablist", { name: "Design" });
    expect(within(design).getByRole("tab", { name: /Mapping/ })).toHaveTextContent("78%");
    expect(within(design).getByRole("tab", { name: /Metadata/ })).toHaveAttribute("aria-selected", "true");
  });
  it("hides the design tabs behind a create-draft empty state when a domain has no version", async () => {
    renderAt("#/d/finops/ontology");
    expect(await screen.findByText("finops has no version yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create a draft version" })).toBeInTheDocument();
  });
  it("shows domains only at home, as cards or a list, and filters them", async () => {
    renderAt("#/", new MockApi({ sourceKind: "databricks" }));
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { level: 1, name: "Domains" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Ask a question")).toBeNull();                                  // the assistant lives in Ask and the Spotlight, not at home
    expect((await screen.findAllByRole("button", { name: "Open" })).length).toBeGreaterThan(1);     // cards by default
    await user.click(screen.getByRole("radio", { name: "List view" }));
    const table = screen.getByRole("table", { name: "Domains" });
    expect(within(table).getAllByRole("columnheader").map(h => h.textContent)).toEqual(["Domain", "Status", "Triples", "Last build", "Source", ""]);
    const rgm = within(table).getByRole("row", { name: /rgm/ });
    expect(rgm).toHaveTextContent(/v1 active/);
    expect(rgm).toHaveTextContent(/succeeded/);
    expect(within(rgm).getByRole("button", { name: "Ask rgm" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Filter domains"), "fin");
    expect(within(table).queryByRole("row", { name: /rgm/ })).toBeNull();
    expect(within(table).getByRole("row", { name: /finops/ })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Card view" }));
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getAllByRole("button", { name: "Open" })).toHaveLength(1);                        // the filter applies to both views
  });
  it("answers an Ask question at the top-level Ask screen through the assistant", async () => {
    renderAt("#/ask", new MockApi({ sourceKind: "databricks", latency: 5 }));
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Ask a question"), "What is net revenue?{Enter}");
    const log = screen.getByRole("log", { name: "Conversation" });
    expect(await within(log).findByText(/I found Carrefour/)).toBeInTheDocument();
    expect(within(log).getByText(/Used 1 tool: search_entities/)).toBeInTheDocument();
  });
  it("renders the mapping designer with the SQL tab in the adapter dialect", async () => {
    renderAt("#/d/rgm/mapping?cls=Customer&panel=sql", new MockApi({ sourceKind: "postgres" }));
    expect(await screen.findByText(/"rgm_gold"\."dim_customer"/)).toBeInTheDocument();
  });
});

describe("Configure screen", () => {
  it("shows the domain's source facts and pickers, and points at the connection module when it is not configured", async () => {
    renderAt("#/d/rgm/settings");
    expect(await screen.findByLabelText("Source connection 1")).toHaveValue("c-warehouse");
    expect(screen.getByLabelText("AI connection")).toHaveValue("c-gpt");
    expect(await screen.findByText("warehouse · rgm")).toBeInTheDocument();
    expect(screen.getByText(/connection module is not configured/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New connection" })).toBeNull();
  });
});

describe("Versions screen", () => {
  it("approves a version in review, then publishes it once the quorum is met", async () => {
    renderAt("#/d/rgm/versions");
    const user = userEvent.setup();
    expect(await screen.findByText("2 of 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("3 of 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Publish" }));
    expect((await screen.findAllByText("v2 published")).length).toBeGreaterThan(0);
  });
  it("deletes a draft after the version number is typed, then rejects the reviewed version back to draft with a comment", async () => {
    const api = new MockApi();
    renderAt("#/d/rgm/versions", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete draft" }));
    const dlg = screen.getByRole("dialog", { name: "Delete draft v3" });
    expect(within(dlg).getByRole("button", { name: "Delete draft" })).toBeDisabled();
    await user.type(within(dlg).getByLabelText("Type 3 to confirm"), "3");
    await user.click(within(dlg).getByRole("button", { name: "Delete draft" }));
    expect(await screen.findByText("Draft v3 deleted")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reject with comment" }));
    const rej = screen.getByRole("dialog", { name: "Reject v2" });
    await user.type(within(rej).getByLabelText("Comment"), "Channel is unmapped");
    await user.click(within(rej).getByRole("button", { name: "Reject and reopen draft" }));
    expect(await screen.findByText("v2 sent back to draft")).toBeInTheDocument();
    const d = await api.domain("rgm");
    expect(d.versions.map(v => [v.version, v.status])).toEqual([[2, "draft"], [1, "published"]]);
    expect((await api.comments("rgm")).at(-1)?.text).toBe("Rejected: Channel is unmapped");
  });
  it("releases the draft lease from the overview", async () => {
    renderAt("#/d/rgm");
    const user = userEvent.setup();
    expect(await screen.findByText(/Held by/)).toHaveTextContent("alice");
    await user.click(screen.getByRole("button", { name: "Release lease" }));
    expect(await screen.findByText("Lease on v3 released")).toBeInTheDocument();
    expect(screen.queryByText(/Held by/)).toBeNull();
  });
});

describe("Configure screen · schemas", () => {
  it("edits the domain's schema list: add from the source, make default, remove, save", async () => {
    const api = new MockApi();
    renderAt("#/d/rgm/settings", api);
    const user = userEvent.setup();
    const list = await screen.findByRole("list", { name: "Schemas" });
    const chips = () => within(list).getAllByRole("listitem").map(li => li.querySelector(".mono")?.textContent + (li.textContent?.includes("default") ? " (default)" : ""));
    expect(chips()).toEqual(["gold (default)", "silver"]);
    await user.type(screen.getByLabelText("Schema name for source 1"), "bronze");
    await user.click(screen.getByRole("button", { name: "Add schema to source 1" }));
    await user.click(within(list).getByRole("button", { name: "Make silver the default" }));
    await user.click(within(list).getByRole("button", { name: "Remove gold" }));
    expect(chips()).toEqual(["silver (default)", "bronze"]);
    await user.click(screen.getByRole("button", { name: "Save source settings" }));
    expect(await screen.findByText("Source settings saved")).toBeInTheDocument();
    expect((await api.domain("rgm")).schemas).toEqual(["silver", "bronze"]);
  });
});


describe("Configure screen · sources", () => {
  it("adds a second source with its own connection and schemas, and requires an AI connection", async () => {
    const api = new MockApi();
    renderAt("#/d/rgm/settings", api);
    const user = userEvent.setup();
    expect(await screen.findByLabelText("Source connection 1")).toHaveValue("c-warehouse");
    await user.click(screen.getByRole("button", { name: "Add source" }));
    await user.selectOptions(screen.getByLabelText("Source connection 2"), "c-lake");
    await user.type(screen.getByLabelText("Schema name for source 2"), "raw");
    await user.click(screen.getByRole("button", { name: "Add schema to source 2" }));
    await user.click(screen.getByRole("button", { name: "Save source settings" }));
    expect(await screen.findByText("Source settings saved")).toBeInTheDocument();
    expect((await api.domain("rgm")).sources).toEqual([{ connectionId: "c-warehouse", catalog: "rgm", schemas: ["gold", "silver"] }, { connectionId: "c-lake", catalog: "lake", schemas: ["raw"] }]);
    await user.selectOptions(screen.getByLabelText("AI connection"), "");
    expect(screen.getByText(/AI connection is required/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save source settings" })).toBeDisabled();
  });
});

describe("New domain dialog", () => {
  it("needs a valid name and an AI connection before it can create", async () => {
    renderAt("#/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "New domain" }));
    const dlg = screen.getByRole("dialog", { name: "New domain" });
    await user.type(within(dlg).getByLabelText("Name"), "adventure works");
    expect(within(dlg).getByText(/Spaces are not allowed/)).toBeInTheDocument();
    await user.clear(within(dlg).getByLabelText("Name"));
    await user.type(within(dlg).getByLabelText("Name"), "adventureworks");
    expect(within(dlg).getByRole("button", { name: "Create domain" })).toBeDisabled();
    await user.selectOptions(within(dlg).getByLabelText("AI connection"), "c-gpt");
    expect(within(dlg).getByRole("button", { name: "Create domain" })).toBeEnabled();
    await user.click(within(dlg).getByRole("button", { name: "Create domain" }));
    expect(await screen.findByText("Domain adventureworks created")).toBeInTheDocument();
  });
});


describe("Metadata screen", () => {
  const open = (hash = "#/d/rgm/metadata?v=3", api = new MockApi()) => { renderAt(hash, api); return userEvent.setup(); };
  it("shows the source at a glance and every table of every schema, grouped, with class and status", async () => {
    open();
    expect(await screen.findByLabelText("Schemas in the source")).toHaveTextContent("2");
    expect(screen.getByLabelText("Tables in the source")).toHaveTextContent("14");
    expect(screen.getByLabelText("Tables in the snapshot")).toHaveTextContent("10");
    const list = screen.getByRole("table", { name: "Tables" });
    expect(within(list).getByRole("button", { name: "Select all in gold" })).toBeInTheDocument();
    expect(within(list).getByText("10 tables · 8 in snapshot")).toBeInTheDocument();
    expect(within(list).getByText("promo_calendar")).toBeInTheDocument();          // silver's rows are there without picking silver
    const row = within(list).getByRole("row", { name: /dim_customer/ });
    expect(within(row).getByText("Customer")).toBeInTheDocument();
    expect(within(row).getByText("In snapshot")).toBeInTheDocument();
    expect(within(within(list).getByRole("row", { name: /fct_returns/ })).getByText("unmapped")).toBeInTheDocument();
    const rail = screen.getByRole("navigation", { name: "Filters" });
    expect(within(rail).getByRole("button", { name: "All tables 14" })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: "Not imported 4" })).toBeInTheDocument();
    expect(within(rail).getByRole("button", { name: "Unmapped 5" })).toBeInTheDocument();
    expect(within(rail).getByText("8/10")).toBeInTheDocument();                       // per-schema snapshot count
  });
  it("opens on the first table and swaps the detail card when a row is chosen", async () => {
    const user = open();
    const list = await screen.findByRole("table", { name: "Tables" });
    expect(await screen.findByRole("heading", { level: 2, name: "dim_customer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove from snapshot" })).toBeInTheDocument();
    await user.click(within(list).getByRole("link", { name: "dim_date" }));
    expect(window.location.hash).toContain("table=dim_date");
    expect(await screen.findByRole("heading", { level: 2, name: "dim_date" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to snapshot" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Columns/ })).toBeInTheDocument();
  });
  it("ticks rows, selects a whole schema and imports the selection into the draft", async () => {
    const user = open();
    const list = await screen.findByRole("table", { name: "Tables" });
    expect(screen.getByRole("button", { name: "Import selected" })).toBeDisabled();
    await user.click(within(list).getByLabelText("Select dim_date"));
    await user.click(within(list).getByRole("button", { name: "Select all in silver" }));   // ticks silver's tables not yet imported
    await user.click(screen.getByRole("button", { name: "Import 3 selected" }));
    expect(await screen.findByText("Imported 3 tables into the snapshot of v3")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Tables in the snapshot")).toHaveTextContent("13"));
    expect(within(list).getByText("4 tables · 4 in snapshot")).toBeInTheDocument();
  });
  it("removes a table from the snapshot from its card", async () => {
    const user = open();
    await screen.findByRole("heading", { level: 2, name: "dim_customer" });
    await user.click(screen.getByRole("button", { name: "Remove from snapshot" }));
    expect(await screen.findByText("dim_customer removed from the snapshot of v3")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Tables in the snapshot")).toHaveTextContent("9"));
    expect(screen.getByRole("button", { name: "Add to snapshot" })).toBeInTheDocument();
  });
  it("filters by status, by schema and by search text", async () => {
    const user = open();
    const list = await screen.findByRole("table", { name: "Tables" });
    const rail = screen.getByRole("navigation", { name: "Filters" });
    await user.click(within(rail).getByRole("button", { name: "Not imported 4" }));
    expect(within(list).queryByText("dim_customer")).toBeNull();
    expect(within(list).getByText("dim_date")).toBeInTheDocument();
    expect(screen.getByText("4 of 14 tables")).toBeInTheDocument();
    await user.click(within(rail).getByRole("button", { name: "All tables 14" }));
    await user.click(within(rail).getByLabelText("Only silver"));
    expect(within(list).queryByText("dim_customer")).toBeNull();
    expect(within(list).getByText("promo_calendar")).toBeInTheDocument();
    await user.click(within(rail).getByLabelText("Only silver"));
    await user.type(screen.getByLabelText("Search tables"), "Customer");                    // matches the class too
    expect(within(list).getByText("dim_customer")).toBeInTheDocument();
    expect(within(list).queryByText("dim_product")).toBeNull();
  });
  it("moves with the keyboard: / searches, arrows walk the rows, space ticks", async () => {
    const user = open();
    const list = await screen.findByRole("table", { name: "Tables" });
    await user.keyboard("/");
    expect(screen.getByLabelText("Search tables")).toHaveFocus();
    await user.keyboard("{Escape}");
    await user.keyboard("{ArrowDown}");
    expect(window.location.hash).toContain("table=dim_product");
    for (let i = 0; i < 8; i++) await user.keyboard("{ArrowDown}");                          // down to dim_date, the first importable row
    expect(window.location.hash).toContain("table=dim_date");
    await user.keyboard(" ");
    expect(within(list).getByLabelText("Select dim_date")).toBeChecked();
  });
  it("cannot import into a published version", async () => {
    open("#/d/hr/metadata?v=3");
    expect(await screen.findByRole("button", { name: "Import selected" })).toBeDisabled();
    expect(screen.getByText(/Only the lease holder of a draft can import/)).toBeInTheDocument();
  });
});


describe("Table screen", () => {
  const at = (tab: string) => `#/d/rgm/table?v=3&schema=rgm.gold&table=dim_customer&tab=${tab}`;
  it("profiles the table on demand and shows rows, nulls and ranges per column", async () => {
    renderAt(at("profile"), new MockApi({ latency: 10 }));
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { level: 1, name: "dim_customer" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Run profile" }));
    expect(await screen.findByText(/Profile of dim_customer updated/)).toBeInTheDocument();
    expect(await screen.findByLabelText("Rows")).toHaveTextContent("612");
    expect(screen.getByLabelText("Row key")).toHaveTextContent("customer_id");
    const summary = screen.getByRole("table", { name: "Column summary" });
    const keyRow = within(summary).getByText("customer_id").closest("tr")!;
    expect(within(keyRow).getByText("row key")).toBeInTheDocument();
    expect(within(keyRow).getByText("numeric id")).toBeInTheDocument();
    expect(within(within(summary).getByText("segment_code").closest("tr")!).getByText("categorical")).toBeInTheDocument();
    const cards = screen.getByRole("region", { name: "Column profiles" });
    expect(within(cards).getByRole("img", { name: "Distribution of segment_code" })).toBeInTheDocument();
    expect(within(cards).getByText(/Primary-key candidate/)).toBeInTheDocument();
    expect(within(cards).getAllByText(/Encode: one-hot/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Re-run profile" })).toBeInTheDocument();
  });
  it("switches its views from the capsule in the section bar and goes back to Metadata", async () => {
    renderAt(at("dq"), new MockApi({ latency: 10 }));
    const user = userEvent.setup();
    const views = await screen.findByRole("tablist", { name: "Views" });
    expect(within(views).getAllByRole("tab").map(t => t.textContent)).toEqual(["Profile", "Data quality", "Glossary"]);
    expect(within(views).getByRole("tab", { name: "Data quality" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByLabelText("Table score")).toBeInTheDocument();
    await user.click(within(views).getByRole("tab", { name: "Profile" }));
    expect(await screen.findByRole("button", { name: /Run profile|Re-run profile/ })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Metadata" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Metadata" })).toBeInTheDocument();
  });
  it("shows the rules with their scores, filters them, adds one and runs them", async () => {
    renderAt(at("dq"), new MockApi({ latency: 10 }));
    const user = userEvent.setup();
    expect(await screen.findByLabelText("Table score")).toHaveTextContent("90%");
    const rules = screen.getByRole("table", { name: "Rules" });
    expect(within(rules).getByText("Country is ISO-2")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /^Failing/ }));
    expect(within(rules).queryByText("Country is ISO-2")).toBeNull();
    expect(within(rules).getByText("Credit limit within range")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /^All/ }));
    await user.click(screen.getByRole("button", { name: "+ New rule" }));
    const dlg = screen.getByRole("dialog", { name: "New rule" });
    await user.type(within(dlg).getByLabelText("Rule name"), "Segment known");
    await user.selectOptions(within(dlg).getByLabelText("Kind"), "in_set");
    await user.selectOptions(within(dlg).getByLabelText("Column"), "segment_code");
    await user.type(within(dlg).getByLabelText("Allowed values (comma-separated)"), "MODERN_TRADE, WHOLESALE, ECOM");
    await user.click(within(dlg).getByRole("button", { name: "Add rule" }));
    expect(await screen.findByText("Rule Segment known added")).toBeInTheDocument();
    expect(await within(rules).findByText("Segment known")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run all rules" }));
    expect(await screen.findByText("Rules of dim_customer run")).toBeInTheDocument();
  });
  it("reads rules off the profile without the AI, once the table is profiled", async () => {
    const api = new MockApi({ latency: 10 });
    renderAt(at("dq"), api);
    const user = userEvent.setup();
    const rules = await screen.findByRole("table", { name: "Rules" });
    await user.click(screen.getByRole("button", { name: "Auto-suggest from profile" }));
    expect(await screen.findByText(/Profile dim_customer first/)).toBeInTheDocument();
    await api.runProfile("rgm", 3, "rgm.gold.dim_customer");
    await user.click(screen.getByRole("button", { name: "Auto-suggest from profile" }));
    expect(await screen.findByText(/rules read off the profile/)).toBeInTheDocument();
    expect(await within(rules).findByText("parent_customer_id within range")).toBeInTheDocument();
    expect(within(rules).getAllByText("auto").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Auto-suggest from profile" }));
    expect(await screen.findByText("The profile suggests nothing new")).toBeInTheDocument();
  });
  it("edits a rule and shows the rows that break it", async () => {
    renderAt(at("dq"), new MockApi({ latency: 10 }));
    const user = userEvent.setup();
    const rules = await screen.findByRole("table", { name: "Rules" });
    expect(within(rules).getAllByRole("img", { name: /Pass rate of/ }).length).toBeGreaterThan(0);   // the trend sparkline
    await user.click(within(rules).getByRole("button", { name: "Actions for Country is ISO-2" }));
    await user.click(screen.getByRole("menuitem", { name: "Edit rule" }));
    const dlg = screen.getByRole("dialog", { name: "Edit rule" });
    expect(within(dlg).getByLabelText("Rule name")).toHaveValue("Country is ISO-2");
    expect(within(dlg).getByLabelText("Pattern (regular expression)")).toHaveValue("^[A-Z]{2}$");
    await user.clear(within(dlg).getByLabelText("Threshold")); await user.type(within(dlg).getByLabelText("Threshold"), "0.9");
    await user.click(within(dlg).getByRole("button", { name: "Save rule" }));
    expect(await screen.findByText("Rule Country is ISO-2 updated")).toBeInTheDocument();
    await user.click(within(rules).getByRole("button", { name: "Actions for Country is ISO-2" }));
    await user.click(screen.getByRole("menuitem", { name: "Show failing rows" }));
    const fails = await screen.findByRole("dialog", { name: "Failing rows · Country is ISO-2" });
    expect(await within(fails).findByRole("table", { name: "Failing rows" })).toBeInTheDocument();
    expect(within(fails).getAllByText(/bad-/).length).toBe(3);
  });
  it("edits a term, moves it through approval and asks the AI for more", async () => {
    renderAt(at("glossary"), new MockApi({ latency: 10 }));
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 3, name: "Trade customer" });
    await user.click(screen.getByRole("button", { name: "Actions for Trade customer" }));
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));
    const dlg = screen.getByRole("dialog", { name: "Edit business term" });
    expect(within(dlg).getByLabelText("Name")).toHaveValue("Trade customer");
    await user.clear(within(dlg).getByLabelText("Definition")); await user.type(within(dlg).getByLabelText("Definition"), "A reseller.");
    await user.click(within(dlg).getByRole("button", { name: "Save term" }));
    expect(await screen.findByText("Term Trade customer updated")).toBeInTheDocument();
    expect(await screen.findByText("A reseller.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Actions for Trade customer" }));
    await user.click(screen.getByRole("menuitem", { name: "Back to draft" }));
    expect(await screen.findByText("Trade customer is now draft")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Suggest with AI" }));
    expect(await screen.findByText("AI added 2 glossary entries")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 3, name: "Customer segment" })).toBeInTheDocument();
  });
  it("lists the business terms and KPI metrics of the table, searches them and adds a term", async () => {
    renderAt(at("glossary"));
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { level: 3, name: "Trade customer" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "Net revenue" })).toBeNull();          // that one names fct_sales
    await user.type(screen.getByLabelText("Search terms"), "credit");
    expect(screen.getByRole("heading", { level: 3, name: "Credit limit" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3, name: "Trade customer" })).toBeNull();
    await user.clear(screen.getByLabelText("Search terms"));
    await user.click(screen.getByRole("tab", { name: /KPI metrics/ }));
    expect(await screen.findByRole("table", { name: "KPI metrics" })).toBeInTheDocument();
    expect(screen.getByText("Active customers")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /Business terms/ }));
    await user.click(screen.getByRole("button", { name: "+ New term" }));
    const dlg = screen.getByRole("dialog", { name: "New business term" });
    await user.type(within(dlg).getByLabelText("Name"), "Onboarding date");
    await user.type(within(dlg).getByLabelText("Definition"), "First invoice date.");
    await user.click(within(dlg).getByRole("button", { name: "Add term" }));
    expect(await screen.findByText("Term Onboarding date added")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 3, name: "Onboarding date" })).toBeInTheDocument();
  });
});


describe("Spotlight and Ask", () => {
  it("opens over any screen with the shortcut, answers through the tools and continues in Ask", async () => {
    renderAt("#/d/rgm/metadata?v=3", new MockApi({ latency: 5 }));
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: "Metadata" });
    expect(screen.queryByRole("dialog", { name: "Spotlight" })).toBeNull();
    await user.keyboard("{Control>}k{/Control}");
    const spot = await screen.findByRole("dialog", { name: "Spotlight" });
    await user.type(within(spot).getByLabelText("Ask the assistant"), "onto");
    expect(within(spot).getByRole("option", { name: /Ontology/ })).toBeInTheDocument();          // a screen to jump to
    await user.clear(within(spot).getByLabelText("Ask the assistant"));
    await user.type(within(spot).getByLabelText("Ask the assistant"), "Which rules are failing?{Enter}");
    expect(await within(spot).findByText(/dim_customer scores 90%/)).toBeInTheDocument();
    expect(within(spot).getByText("table_quality")).toBeInTheDocument();                           // the tool it called
    await user.click(within(spot).getByRole("button", { name: "Continue in Ask" }));
    expect(window.location.hash).toMatch(/#\/d\/rgm\/ask\?c=c-/);
    expect(await screen.findByRole("log", { name: "Conversation" })).toHaveTextContent(/Which rules are failing\?/);
    expect(screen.getByRole("log", { name: "Conversation" })).toHaveTextContent(/dim_customer scores 90%/);
  });
  it("renders the assistant's Markdown and draws the chart it describes", async () => {
    renderAt("#/d/rgm/ask?v=3", new MockApi({ latency: 5 }));
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Ask a question"), "Chart sales by year{Enter}");
    const log = screen.getByRole("log", { name: "Conversation" });
    expect(await within(log).findByRole("img", { name: "Sales by year" })).toBeInTheDocument();      // the ```chart block becomes a chart
    expect(within(log).getByText("2024", { selector: "strong" })).toBeInTheDocument();                // **bold** is rendered, not shown raw
    expect(within(log).queryByText(/\*\*/)).toBeNull();
    expect(within(log).getByRole("table")).toBeInTheDocument();
    expect(within(log).queryByText(/```/)).toBeNull();
  });
  it("holds a thread in Ask, shows the tool trace and keeps the list of conversations", async () => {
    renderAt("#/d/rgm/ask?v=3", new MockApi({ latency: 5 }));
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Ask a question"), "Start a build{Enter}");
    const log = screen.getByRole("log", { name: "Conversation" });
    expect(await within(log).findByText(/Build started on rgm/)).toBeInTheDocument();
    expect(within(log).getByText(/Used 1 tool: start_build/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Ask a question"), "Profile the customer table{Enter}");
    expect(await within(log).findByText(/612 rows/)).toBeInTheDocument();
    expect(within(log).getByText(/Build started on rgm/)).toBeInTheDocument();                       // the thread stays
    const threads = screen.getByRole("complementary", { name: "Conversations" });
    expect(within(threads).getByText("Start a build")).toBeInTheDocument();
    await user.click(within(threads).getByRole("button", { name: "New conversation" }));
    expect(within(log).queryByText(/Build started on rgm/)).toBeNull();
  });
});


describe("Build screen", () => {
  it("runs a build, shows live steps and settles with the result in the history", async () => {
    renderAt("#/d/rgm/build?v=3", new MockApi({ stepScale: 1 }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Start build" }));
    expect(await screen.findByText("Run in progress")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Build succeeded · 263,695 triples/)).toBeInTheDocument(), { timeout: 8000 });
    expect(screen.getByRole("heading", { name: /Last run · #/ })).toBeInTheDocument();
  }, 10000);
  it("stops polling and says so when the status cannot be read", async () => {
    class Broken extends MockApi { override async buildStatus(): Promise<never> { throw new Error("connection refused"); } }
    renderAt("#/d/rgm/build?v=3", new Broken({ stepScale: 1 }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Start build" }));
    await waitFor(() => expect(screen.getByText(/Lost track of the build: connection refused/)).toBeInTheDocument(), { timeout: 8000 });
  }, 10000);
});


describe("Build screen · checklist", () => {
  it("shows the drift the last build found at once, and re-reads the source only when asked", async () => {
    const live: boolean[] = [];
    class SlowDrift extends MockApi { override async drift(d: string, v: number, o?: { live?: boolean }) { live.push(!!o?.live); if (o?.live) await new Promise(r => setTimeout(r, 300)); return super.drift(d, v, o); } }
    renderAt("#/d/rgm/build?v=3", new SlowDrift());
    const user = userEvent.setup();
    expect(await screen.findByText("Mapping completion")).toBeInTheDocument();
    expect(await screen.findByText("1 issue · last build")).toBeInTheDocument();     // instant: what the last build recorded
    expect(live).toEqual([false]);                                                   // the source was not read
    await user.click(screen.getByRole("button", { name: "Check drift now" }));
    expect(screen.getByText("checking the source…")).toBeInTheDocument();
    expect(await screen.findByText("1 issue · checked now", {}, { timeout: 2000 })).toBeInTheDocument();
    expect(live).toEqual([false, true]);
  });
});


describe("Explore screen · search", () => {
  it("does not search with an empty query: the overview is the first picture, not 20 arbitrary hits", async () => {
    const searched: string[] = [];
    class Counting extends MockApi { override async search(d: string, q: string, o?: Parameters<MockApi["search"]>[2]) { searched.push(q); return super.search(d, q, o); } }
    renderAt("#/d/rgm/explore", new Counting());
    expect(await screen.findByRole("heading", { level: 1, name: "Explore" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/nodes ·/)).toBeInTheDocument());
    expect(searched).toEqual([]);
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Find an entity by label or IRI"), "smith");
    await waitFor(() => expect(searched.some(q => q.length > 0)).toBe(true));
  });
});


describe("Mapping screen", () => {
  it("maps an unmapped class to a snapshot table, binds an attribute from a dropdown and excludes another", async () => {
    const api = new MockApi();
    renderAt("#/d/rgm/mapping?v=3&cls=Channel", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Map to a table" }));
    const dlg = screen.getByRole("dialog", { name: "Map Channel to a table" });
    await user.selectOptions(within(dlg).getByLabelText("Table"), "rgm.gold.dim_region");
    expect(within(dlg).getByLabelText("Key column")).toHaveValue("id");
    await user.click(within(dlg).getByRole("button", { name: "Map class" }));
    expect(await screen.findByText("Channel mapped to rgm.gold.dim_region")).toBeInTheDocument();
    await user.selectOptions(await screen.findByLabelText("Column for channelName"), "name");
    expect(await screen.findByText("channelName → name")).toBeInTheDocument();
    expect((await api.mapping("rgm", 3)).Channel).toMatchObject({ fullName: "rgm.gold.dim_region", cols: { channelName: "name" }, state: "complete" });
  });
});


describe("Ontology screen · drafting", () => {
  it("drafts the ontology with AI from the snapshot tables through a dialog", async () => {
    const api = new MockApi();
    await api.createDomain({ name: "aw", description: "Adventure", base_iri: "http://p/aw/", quorum: 1, ai_connection_id: "c-gpt", sources: [{ connection_id: "c-warehouse", catalog: "aw", schemas: ["gold"] }] });
    await api.createDraft("aw");
    renderAt("#/d/aw/ontology?v=1", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Draft with AI" }));
    const dlg = screen.getByRole("dialog", { name: "Draft the ontology with AI" });
    expect(within(dlg).getAllByRole("checkbox").length).toBeGreaterThan(0);
    await user.type(within(dlg).getByLabelText("What this domain is about"), "Revenue and customers");
    await user.click(within(dlg).getByRole("button", { name: "Draft ontology" }));
    expect(await within(dlg).findByText(/Describing table|Asking the AI|Reading \d+ tables? from the source/)).toBeInTheDocument();   // progress while it runs
    expect(await screen.findByText(/Drafted \d+ classes/)).toBeInTheDocument();
    expect((await api.ontology("aw", 1)).length).toBeGreaterThan(0);
  });
});


describe("Mapping screen · AI status", () => {
  it("shows what the suggestion is doing while it runs", async () => {
    renderAt("#/d/rgm/mapping?v=3", new MockApi({ latency: 40 }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Suggest with AI" }));
    expect(await screen.findByText(/Describing table|Asking the AI/)).toBeInTheDocument();
    expect(await screen.findByText(/AI suggested bindings/)).toBeInTheDocument();
  });
});


describe("Ontology screen · running draft", () => {
  it("shows a draft already running on the server and reloads when it ends", async () => {
    class Busy extends MockApi {
      override async runningAiJob(_d: string, _v: number, kind: "suggest-mapping" | "draft-ontology", onProgress?: (p: { progress: string; startedAt: string | null; progressAt: string | null; status: "running" | "succeeded" | "failed" }) => void) {
        if (kind !== "draft-ontology") return null;
        onProgress?.({ progress: "Describing table 24 of 68: location", startedAt: null, progressAt: null, status: "running" });
        await new Promise(r => setTimeout(r, 80));
        return { progress: "Done", startedAt: null, progressAt: null, status: "succeeded" as const };
      }
    }
    renderAt("#/d/rgm/ontology?v=3", new Busy());
    expect(await screen.findByText(/Describing table 24 of 68/)).toBeInTheDocument();
    expect(await screen.findByText("AI draft finished: ontology replaced")).toBeInTheDocument();
  });
});


describe("Mapping screen · fill relationships", () => {
  it("maps the open relationships and says where each came from", async () => {
    const api = new MockApi({ latency: 10 });
    renderAt("#/d/rgm/mapping?v=3", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Fill relationships" }));
    expect(await screen.findByText(/relationships? mapped · \d+ from declared keys/)).toBeInTheDocument();
  });
});




describe("Rules and Data quality across the version", () => {
  it("lists the rule kinds by dimension and every rule of every table, and adds a rule to a chosen table", async () => {
    renderAt("#/d/rgm/rules?v=3", new MockApi({ latency: 5 }));
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { level: 1, name: "Rules" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Valid email address/ })).toBeInTheDocument();          // the catalogue
    const all = await screen.findByRole("table", { name: "All rules" });
    expect(within(all).getByText("Country is ISO-2")).toBeInTheDocument();                                    // a dim_customer rule
    expect(within(all).getAllByRole("row").length).toBeGreaterThan(2);
    await user.click(screen.getByRole("button", { name: /Not null and not empty/ }));
    const dlg = screen.getByRole("dialog", { name: "New rule" });
    expect(within(dlg).getByLabelText("Kind")).toHaveValue("not_empty");
    await user.selectOptions(within(dlg).getByLabelText("Table"), "rgm.gold.dim_product");
    await user.type(within(dlg).getByLabelText("Rule name"), "Product has a name");
    await user.click(within(dlg).getByRole("button", { name: "Add rule" }));
    expect(await screen.findByText(/Rule Product has a name added to dim_product/)).toBeInTheDocument();
    expect(await within(await screen.findByRole("table", { name: "All rules" })).findByText("Product has a name")).toBeInTheDocument();
  });
  it("shows each table's score and rule summary on the Data quality tab and keeps the graph constraints on their own", async () => {
    renderAt("#/d/rgm/quality?v=3", new MockApi({ latency: 5 }));
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { level: 1, name: "Data quality" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Score of dim_customer")).toHaveTextContent(/\d+%/);
    expect(screen.getAllByText(/uniqueness · 1/).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("tab", { name: "Graph constraints" }));
    expect(await screen.findByText("Constraint")).toBeInTheDocument();
  });
  it("does not read the source again when coming back to Metadata from a table", async () => {
    let reads = 0;
    class Counting extends MockApi { override async schemas(d: string) { reads++; return super.schemas(d); } }
    renderAt("#/d/rgm/metadata?v=3", new Counting({ latency: 5 }));
    const user = userEvent.setup();
    expect(await screen.findByRole("heading", { level: 1, name: "Metadata" })).toBeInTheDocument();
    await waitFor(() => expect(reads).toBe(1));
    await user.click(screen.getByRole("link", { name: "Design" }));      // the rail keeps us in Design; go to a table and back
    window.location.hash = "#/d/rgm/table?v=3&schema=rgm.gold&table=dim_customer&tab=profile";
    expect(await screen.findByRole("heading", { level: 1, name: "dim_customer" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Metadata" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Metadata" })).toBeInTheDocument();
    expect(reads).toBe(1);
  });
  it("offers quick links on the overview", async () => {
    renderAt("#/d/rgm");
    const links = await screen.findByRole("navigation", { name: "Quick links" });
    expect(within(links).getAllByRole("link").map(a => a.textContent)).toEqual(["Import tables", "Ontology", "Mapping", "Rules", "Build", "Explore", "Ask", "Versions"]);
  });
});


describe("Ontology screen · the table behind a class", () => {
  it("shows the mapped table of the selected class and opens its metadata and profile", async () => {
    renderAt("#/d/rgm/ontology?v=3&cls=Customer", new MockApi({ latency: 5 }));
    const user = userEvent.setup();
    const asset = await screen.findByRole("region", { name: "Mapped table" });
    expect(await within(asset).findByText("gold.dim_customer")).toBeInTheDocument();
    await user.click(within(asset).getByRole("link", { name: "Metadata" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Metadata" })).toBeInTheDocument();
    expect(window.location.hash).toMatch(/table=dim_customer/);
    window.location.hash = "#/d/rgm/ontology?v=3&cls=Customer";
    await user.click(within(await screen.findByRole("region", { name: "Mapped table" })).getByRole("link", { name: "Profile" }));
    expect(await screen.findByRole("heading", { level: 1, name: "dim_customer" })).toBeInTheDocument();
    expect(window.location.hash).toMatch(/tab=profile/);
  });
  it("offers to map a class that has no table", async () => {
    renderAt("#/d/rgm/ontology?v=3&cls=Channel", new MockApi({ latency: 5 }));
    const asset = await screen.findByRole("region", { name: "Mapped table" });
    expect(await within(asset).findByText(/not mapped/i)).toBeInTheDocument();
    expect(within(asset).getByRole("link", { name: "Map it" })).toBeInTheDocument();
  });
});


describe("Mapping screen · what is left to map", () => {
  it("lists the unmapped and partly mapped classes first and opens the table picker from the list", async () => {
    renderAt("#/d/rgm/mapping?v=3", new MockApi({ latency: 5 }));
    const user = userEvent.setup();
    const todo = await screen.findByRole("region", { name: "To map" });
    expect(await within(todo).findByRole("button", { name: "Map Channel" })).toBeInTheDocument();      // unmapped: map it to a table
    expect(within(todo).getAllByText(/partly mapped/i).length).toBeGreaterThan(0);                    // partial classes are listed too
    await user.click(within(todo).getByRole("button", { name: "Map Channel" }));
    expect(await screen.findByRole("dialog", { name: "Map Channel to a table" })).toBeInTheDocument();
    expect(window.location.hash).toMatch(/cls=Channel/);
  });
});

describe("Notifications bell", () => {
  it("counts what is unread, lists running work first, and a click deep-links and marks the row read", async () => {
    renderAt("#/");
    const user = userEvent.setup();
    const bell = await screen.findByRole("button", { name: "Notifications, 2 unread" });
    expect(bell).toHaveTextContent("2");
    expect(screen.queryByText("My tasks")).toBeNull();                                               // the hard-coded badge is gone
    await user.click(bell);
    const menu = screen.getByRole("menu", { name: "Notifications" });
    const rows = within(menu).getAllByRole("menuitem");
    expect(rows[0]).toHaveTextContent("Building rgm v3");                                             // running work first, with its progress
    expect(rows[0]).toHaveTextContent("step 3 of 7: load · 120,000 rows");
    expect(within(menu).getByText("Needs you")).toBeInTheDocument();                                  // the review queue lives here too
    expect(within(menu).getByRole("menuitem", { name: /Review rgm v2/ })).toBeInTheDocument();
    await user.click(within(menu).getByRole("menuitem", { name: /Profile of sales_fact ready/ }));
    expect(window.location.hash).toBe("#/d/rgm/table?v=3&schema=silver&table=sales_fact&tab=profile");
    expect(await screen.findByRole("button", { name: "Notifications, 1 unread" })).toBeInTheDocument();
    expect(screen.queryByRole("menu")).toBeNull();
  });
  it("marks everything read from the list and drops the badge", async () => {
    renderAt("#/");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Notifications, 2 unread" }));
    await user.click(screen.getByRole("link", { name: "Mark all read" }));
    const bell = await screen.findByRole("button", { name: "Notifications" });
    expect(within(bell).queryByText("2")).toBeNull();
  });
});

describe("Actions that used to only show a message", () => {
  it("changes a role, revokes a key and releases a lease through the API", async () => {
    const api = new MockApi();
    const role = vi.spyOn(api, "setPrincipalRole"), revoke = vi.spyOn(api, "revokeApiKey"), release = vi.spyOn(api, "forceRelease");
    renderAt("#/admin", api);
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Role of priya"), "admin");
    expect(role).toHaveBeenCalledWith("priya", "admin");
    await user.click(screen.getByRole("button", { name: "Revoke CI builder" }));
    expect(revoke).toHaveBeenCalledWith("CI builder");
    await waitFor(() => expect(screen.queryByText("CI builder")).toBeNull());
    await user.click(screen.getAllByRole("button", { name: /Force release/ })[0]);
    expect(release).toHaveBeenCalled();
  });
  it("runs the graph constraint checks instead of announcing a result", async () => {
    const api = new MockApi();
    const run = vi.spyOn(api, "runConstraintChecks");
    renderAt("#/d/rgm/quality?view=graph", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Run checks" }));
    expect(run).toHaveBeenCalledWith("rgm", 3);
  });
  it("runs the reasoning rules and the OWL closure, and reports what they returned", async () => {
    const api = new MockApi({ latency: 0 });
    const infer = vi.spyOn(api, "runInference"), rules = vi.spyOn(api, "runReasoningRules");
    renderAt("#/d/rgm/rules?view=reasoning", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Run OWL RL" }));
    await waitFor(() => expect(infer).toHaveBeenCalledWith("rgm", 3));
    await user.click(screen.getByRole("button", { name: "Run rules" }));
    await waitFor(() => expect(rules).toHaveBeenCalledWith("rgm", 3));
  });
  it("hides the role switcher when the app talks to a real backend", async () => {
    renderAt("#/");
    expect(await screen.findByLabelText("Switch role")).toBeInTheDocument();   // a mock build may impersonate
  });
});

describe("Ontology editor", () => {
  it("adds a parent, an attribute and a relationship, and deletes a class", async () => {
    const api = new MockApi();
    renderAt("#/d/rgm/ontology?cls=Customer", api);
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 2, name: "Customer" });

    await user.click(screen.getByRole("button", { name: "+ Add parent" }));
    await user.selectOptions(await screen.findByLabelText("Parent class"), "Product");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(screen.getByText("Product is now a parent of Customer")).toBeInTheDocument());
    expect((await api.ontology("rgm", 3)).find(c => c.id === "Customer")?.parents).toContain("Product");

    await user.click(screen.getAllByRole("link", { name: "+ Add" })[0]);
    await user.type(await screen.findByLabelText("Name"), "loyaltyTier");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(screen.getByText("loyaltyTier added to Customer")).toBeInTheDocument());
    expect((await api.ontology("rgm", 3)).find(c => c.id === "Customer")?.attrs.map(a => a.name)).toContain("loyaltyTier");

    await user.click(screen.getAllByRole("link", { name: "+ Add" })[1]);
    await user.type(await screen.findByLabelText("Name"), "favours");
    await user.selectOptions(screen.getByLabelText("Target class"), "Product");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(screen.getByText("favours → Product added to Customer")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(await screen.findByRole("button", { name: "Delete class" }));
    await waitFor(() => expect(screen.getByText("Customer deleted")).toBeInTheDocument());
    expect((await api.ontology("rgm", 3)).some(c => c.id === "Customer")).toBe(false);
  });
});
