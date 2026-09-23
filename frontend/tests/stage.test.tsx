import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Stage, colorFor, layoutNodes } from "@/components/Stage";

const nodes = [
  { id: "Customer", label: "Customer", glyph: "C", x: 0, y: 0, fill: "#2249FF", selected: true, props: 4 },
  { id: "Sale", label: "Sale", glyph: "S", x: 0, y: 0, fill: "#2249FF", props: 6 },
  { id: "Product", label: "Product", glyph: "P", x: 0, y: 0, fill: "#2249FF" },
  { id: "Region", label: "Region", glyph: "R", x: 0, y: 0, fill: "#2249FF" },   // nothing links to it
];
const edges = [{ from: "Sale", to: "Customer", label: "soldTo" }, { from: "Sale", to: "Product", label: "ofProduct" }];

describe("Stage layout", () => {
  it("force: settles every node at a finite, distinct spot, and pins a pinned node at the origin", () => {
    const pos = layoutNodes([{ ...nodes[0], pin: true }, ...nodes.slice(1)], edges, "force", "TB", 400);
    expect(Object.values(pos).every(p => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
    expect(pos.Customer).toEqual({ x: 0, y: 0 });
    const spots = new Set(Object.values(pos).map(p => `${Math.round(p.x)},${Math.round(p.y)}`));
    expect(spots.size).toBe(4);
    const dist = (a: string, b: string) => Math.hypot(pos[a].x - pos[b].x, pos[a].y - pos[b].y);
    expect(dist("Sale", "Customer")).toBeLessThan(dist("Region", "Customer") + 1);   // linked nodes sit closer than unlinked ones
    expect(layoutNodes(nodes, edges, "force", "TB", 400)).toEqual(layoutNodes(nodes, edges, "force", "TB", 400));   // deterministic
  });
  it("dagre: ranks linked classes", () => {
    const pos = layoutNodes(nodes, edges, "dagre", "TB", 400);
    expect(pos.Sale.y).toBeLessThan(pos.Customer.y);
    expect(pos.Customer.y).toBe(pos.Product.y);
  });
  it("keeps given percentages", () => {
    const pos = layoutNodes([{ ...nodes[0], x: 50, y: 50 }, { ...nodes[1], x: 80, y: 20 }], [edges[0]], "given", "TB", 500);
    expect(pos.Sale.x).toBeGreaterThan(pos.Customer.x); expect(pos.Sale.y).toBeLessThan(pos.Customer.y);
  });
  it("colours a class the same every time and different classes differently", () => {
    expect(colorFor("Customer")).toBe(colorFor("Customer"));
    expect(colorFor("Customer")).toMatch(/^#[0-9A-F]{6}$/i);
    expect(new Set(["Customer", "Sale", "Product", "Store"].map(colorFor)).size).toBeGreaterThan(2);
  });
});

describe("Stage", () => {
  it("renders every node as a bubble with the name inside, with tools, and reports clicks", () => {
    const onSelect = vi.fn();
    render(<Stage nodes={nodes} edges={edges} height={400} />);
    render(<Stage nodes={nodes} edges={edges} height={400} onSelect={onSelect} />);
    const bubbles = screen.getAllByRole("button", { hidden: true }).filter(b => b.classList.contains("bubble"));   // hidden until React Flow measures them, which jsdom never does
    expect(bubbles.map(b => b.getAttribute("aria-label"))).toEqual(expect.arrayContaining(["Customer", "Sale", "Product", "Region"]));
    for (const el of document.querySelectorAll(".react-flow__node")) expect((el as HTMLElement).style.transform).toMatch(/translate\(-?[\d.]+px, ?-?[\d.]+px\)/);
    fireEvent.click(bubbles.filter(b => b.getAttribute("aria-label") === "Sale").at(-1)!);
    expect(onSelect).toHaveBeenCalledWith("Sale");
    expect(screen.getAllByRole("button", { name: "Fit" }).length).toBe(2);
    expect(screen.getAllByRole("button", { name: "Switch layout" }).length).toBe(2);
  });
  it("offers no relayout for a given layout", () => {
    render(<Stage nodes={nodes.slice(0, 2)} edges={[edges[0]]} height={500} layout="given" />);
    expect(screen.queryByRole("button", { name: "Switch layout" })).toBeNull();
  });
});

describe("Stage focus", () => {
  it("shows the whole graph first, even when the selected class has no relationships", () => {
    const many = Array.from({ length: 40 }, (_, i) => ({ id: `C${i}`, label: `Class${i}`, glyph: "C", x: 0, y: 0, fill: "#2249FF", selected: i === 7 }));
    render(<Stage nodes={many} edges={[{ from: "C0", to: "C1", label: "a" }]} height={400} />);
    expect(document.querySelectorAll(".react-flow__node").length).toBe(40);
    expect(screen.getByText("40 nodes · 1 edge")).toBeInTheDocument();
  });
  it("isolates the selected node's neighbourhood on demand and comes back to everything", async () => {
    const many = Array.from({ length: 40 }, (_, i) => ({ id: `C${i}`, label: `Class${i}`, glyph: "C", x: 0, y: 0, fill: "#2249FF", selected: i === 0 }));
    const links = [{ from: "C0", to: "C1", label: "a" }, { from: "C2", to: "C0", label: "b" }, { from: "C5", to: "C6", label: "c" }];
    render(<Stage nodes={many} edges={links} height={400} />);
    expect(document.querySelectorAll(".react-flow__node").length).toBe(40);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Focus on selection" }));
    expect(document.querySelectorAll(".react-flow__node").length).toBe(3);          // C0 and its two neighbours
    expect(screen.getByText(/Class0 and its neighbours \(40 in all\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show all" }));
    expect(document.querySelectorAll(".react-flow__node").length).toBe(40);
  });
});

describe("Stage overview and drill-down", () => {
  const hubby = [
    { id: "Hub", label: "Hub", glyph: "H", x: 0, y: 0, fill: "#111", group: "a" },
    ...Array.from({ length: 6 }, (_, i) => ({ id: `L${i}`, label: `Leaf${i}`, glyph: "L", x: 0, y: 0, fill: "#222", group: i % 2 ? "a" : "b" })),
    { id: "Lonely", label: "Lonely", glyph: "L", x: 0, y: 0, fill: "#333", group: "b" },
  ];
  const links = Array.from({ length: 6 }, (_, i) => ({ from: "Hub", to: `L${i}`, label: "has" }));
  const groups = [{ id: "a", label: "Group A", color: "#111" }, { id: "b", label: "Group B", color: "#222" }];
  it("sizes bubbles by how connected they are and shows the whole graph with counts", () => {
    render(<Stage nodes={hubby} edges={links} height={400} groups={groups} />);
    const size = (label: string) => parseFloat((screen.getAllByRole("button", { hidden: true }).find(b => b.getAttribute("aria-label") === label) as HTMLElement).style.width);
    expect(size("Hub")).toBeGreaterThan(size("Leaf0"));
    expect(size("Leaf0")).toBeGreaterThan(size("Lonely") - 1);
    expect(document.querySelectorAll(".react-flow__node").length).toBe(8);
    expect(screen.getByText("8 nodes · 6 edges")).toBeInTheDocument();
  });
  it("hides a group from the legend and spotlights the selected node's neighbourhood", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<Stage nodes={hubby.map(n => ({ ...n, selected: n.id === "L0" }))} edges={links} height={400} groups={groups} />);
    const dim = () => [...document.querySelectorAll(".bubble.dim")].map(b => b.getAttribute("aria-label"));
    expect(dim()).toEqual(expect.arrayContaining(["Leaf1", "Lonely"]));   // not neighbours of Leaf0
    expect(dim()).not.toContain("Hub");
    await user.click(screen.getByLabelText("Show Group B"));
    expect(document.querySelectorAll(".react-flow__node").length).toBe(4);   // Hub, Leaf1, Leaf3, Leaf5
    expect(screen.getByText("4 nodes · 3 edges")).toBeInTheDocument();
  });
  it("finds a node by name and reports double-clicks as expansion", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    const onSelect = vi.fn(), onExpand = vi.fn();
    render(<Stage nodes={hubby} edges={links} height={400} onSelect={onSelect} onExpand={onExpand} />);
    await user.type(screen.getByLabelText("Find a node"), "lea{Enter}");
    expect(onSelect).toHaveBeenCalledWith("L0");
    fireEvent.doubleClick(screen.getAllByRole("button", { hidden: true }).find(b => b.getAttribute("aria-label") === "Hub")!);
    expect(onExpand).toHaveBeenCalledWith("Hub");
  });
});
