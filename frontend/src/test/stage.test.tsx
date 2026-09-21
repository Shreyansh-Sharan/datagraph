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
  it("shows everything when the selected class has no relationships", () => {
    const many = Array.from({ length: 40 }, (_, i) => ({ id: `C${i}`, label: `Class${i}`, glyph: "C", x: 0, y: 0, fill: "#2249FF", selected: i === 7 }));
    render(<Stage nodes={many} edges={[{ from: "C0", to: "C1", label: "a" }]} height={400} />);
    expect(document.querySelectorAll(".react-flow__node").length).toBe(40);
    expect(screen.getByText(/Class7 has no relationships · showing all 40/)).toBeInTheDocument();
  });
  it("opens a big graph on the selected node's neighbourhood and can show everything", async () => {
    const many = Array.from({ length: 40 }, (_, i) => ({ id: `C${i}`, label: `Class${i}`, glyph: "C", x: 0, y: 0, fill: "#2249FF", selected: i === 0 }));
    const links = [{ from: "C0", to: "C1", label: "a" }, { from: "C2", to: "C0", label: "b" }, { from: "C5", to: "C6", label: "c" }];
    render(<Stage nodes={many} edges={links} height={400} />);
    expect(document.querySelectorAll(".react-flow__node").length).toBe(3);          // C0 and its two neighbours
    expect(screen.getByText(/3 of 40 shown/)).toBeInTheDocument();
    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.setup().click(screen.getByRole("button", { name: "Show all" }));
    expect(document.querySelectorAll(".react-flow__node").length).toBe(40);
  });
});
