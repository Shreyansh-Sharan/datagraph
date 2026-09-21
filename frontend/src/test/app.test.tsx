import { describe, expect, it } from "vitest";
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
  it("opens a domain with the side nav, version picker and readiness card", async () => {
    renderAt("#/d/rgm");
    expect(await screen.findByRole("heading", { level: 2, name: /Readiness · v3/ })).toBeInTheDocument();
    const nav = screen.getByRole("complementary");
    expect(within(nav).getByText("Mapping")).toBeInTheDocument();
    expect(within(nav).getByText("78%")).toBeInTheDocument();
  });
  it("hides the design tabs behind a create-draft empty state when a domain has no version", async () => {
    renderAt("#/d/finops/ontology");
    expect(await screen.findByText("finops has no version yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create a draft version" })).toBeInTheDocument();
  });
  it("answers an Ask question inline", async () => {
    renderAt("#/");
    const user = userEvent.setup();
    await screen.findByText("Revenue growth management");
    await user.type(screen.getByLabelText("Ask a question"), "What is net revenue?{Enter}");
    expect(await screen.findByText(/owned by marc/)).toBeInTheDocument();
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
    expect(await screen.findByText("Databricks · finops_metadata")).toBeInTheDocument();
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


describe("Metadata screen · scan", () => {
  it("imports the ticked tables into the draft's snapshot", async () => {
    const api = new MockApi();
    renderAt("#/d/rgm/metadata?v=3", api);
    const user = userEvent.setup();
    expect(await screen.findByText("8 in snapshot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import selected" })).toBeDisabled();
    await user.click(screen.getByLabelText("Select dim_date"));
    await user.click(screen.getByLabelText("Select fct_returns"));
    await user.click(screen.getByRole("button", { name: "Import 2 selected" }));
    expect(await screen.findByText("Imported 2 tables into the snapshot of v3")).toBeInTheDocument();
    expect(await screen.findByText("10 in snapshot")).toBeInTheDocument();
  });
  it("cannot import into a published version", async () => {
    renderAt("#/d/hr/metadata?v=3");
    expect(await screen.findByRole("button", { name: "Import selected" })).toBeDisabled();
    expect(screen.getByText(/Only the lease holder of a draft can import/)).toBeInTheDocument();
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
