import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
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
  it("shows the domain's source facts, the connection pickers and the connector form", async () => {
    renderAt("#/d/rgm/settings");
    const user = userEvent.setup();
    expect(await screen.findByLabelText("Source connection")).toHaveValue("c-warehouse");
    expect(screen.getByLabelText("AI connection")).toHaveValue("c-gpt");
    expect(await screen.findByText("Databricks · finops_metadata")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "New connection" }));
    expect(await screen.findByRole("dialog", { name: "New connection" })).toBeInTheDocument();
    expect(screen.getByLabelText("Workspace host")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Kind"), "sqlserver");
    expect(await screen.findByLabelText("Driver")).toHaveValue("auto");
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Test" }));
    expect(await screen.findByText("Driver not installed")).toBeInTheDocument();
  });
});
