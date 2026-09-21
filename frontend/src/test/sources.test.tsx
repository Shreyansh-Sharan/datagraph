// The Configure screen's source rows take the catalog from the picked connection and offer its
// schemas from the connection module's browse API (the hub), not from the deployment's source.
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "@/App";
import { MockApi } from "@/api/mock";

vi.mock("@/config", () => ({ CONNECTIONS_URL: "/hub" }));

const hubCalls: string[] = [];
globalThis.fetch = (async (url: string) => {
  hubCalls.push(url);
  if (url.startsWith("/hub/connections/c-lake/browse")) return new Response(JSON.stringify([{ name: "raw", kind: "schema", attributes: {}, has_children: true }, { name: "staging", kind: "schema", attributes: {}, has_children: true }]));
  if (url.startsWith("/hub/connections/c-warehouse/browse")) return new Response(JSON.stringify({ detail: "warehouse is stopped" }), { status: 502 });
  if (url.startsWith("/hub/connection-types") || url.startsWith("/hub/connections")) return new Response("[]");
  return new Response(JSON.stringify({ detail: `no route ${url}` }), { status: 404 });
}) as typeof fetch;

describe("Configure screen · sources from the connection module", () => {
  it("takes the catalog from the picked connection and lists its schemas from the hub's browse API", async () => {
    const api = new MockApi();
    window.location.hash = "#/d/rgm/settings";
    render(<App api={api} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add source" }));
    await user.selectOptions(screen.getByLabelText("Source connection 2"), "c-lake");
    expect(screen.getByText("lake", { selector: ".mono" })).toBeInTheDocument();          // catalog = the connection's database
    const pick = await screen.findByLabelText("Schema for source 2");
    expect(within(pick).getAllByRole("option").map(o => o.textContent)).toEqual(["Add a schema…", "raw", "staging"]);
    await user.selectOptions(pick, "raw");
    expect(within(pick).getAllByRole("option").map(o => o.textContent)).toEqual(["Add a schema…", "staging"]);
    await user.click(screen.getByRole("button", { name: "Save source settings" }));
    expect(await screen.findByText("Source settings saved")).toBeInTheDocument();
    expect((await api.domain("rgm")).sources[1]).toEqual({ connectionId: "c-lake", catalog: "lake", schemas: ["raw"] });
    expect(hubCalls.filter(u => u.startsWith("/hub/connections/c-lake/browse")).length).toBe(1);   // browsed once, then cached
  });
  it("falls back to a typed schema name when the hub cannot browse the connection", async () => {
    window.location.hash = "#/d/rgm/settings";
    render(<App api={new MockApi()} />);
    expect(await screen.findByText(/warehouse is stopped/)).toBeInTheDocument();
    expect(screen.getByLabelText("Schema name for source 1")).toBeInTheDocument();
  });
});
