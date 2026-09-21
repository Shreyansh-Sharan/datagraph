import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Stage, layoutNodes } from "@/components/Stage";

const nodes = [
  { id: "Customer", label: "Customer", glyph: "C", x: 0, y: 0, fill: "#2249FF", selected: true, props: 4 },
  { id: "Sale", label: "Sale", glyph: "S", x: 0, y: 0, fill: "#2249FF", props: 6 },
  { id: "Product", label: "Product", glyph: "P", x: 0, y: 0, fill: "#2249FF" },
  { id: "Region", label: "Region", glyph: "R", x: 0, y: 0, fill: "#2249FF" },   // nothing links to it
];
const edges = [{ from: "Sale", to: "Customer", label: "soldTo" }, { from: "Sale", to: "Product", label: "ofProduct" }];

describe("Stage layout", () => {
  it("ranks linked classes with dagre and packs unlinked ones in a grid below", () => {
    const pos = layoutNodes(nodes, edges, "dagre", "TB", 400);
    expect(Object.values(pos).every(p => Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
    expect(pos.Sale.y).toBeLessThan(pos.Customer.y);                 // source above its targets
    expect(pos.Customer.y).toBe(pos.Product.y);                      // same rank
    expect(pos.Region.y).toBeGreaterThan(pos.Customer.y);            // isolated: below the connected part
    const lr = layoutNodes(nodes, edges, "dagre", "LR", 400);
    expect(lr.Sale.x).toBeLessThan(lr.Customer.x);
  });
  it("keeps given percentages for a star", () => {
    const pos = layoutNodes([{ ...nodes[0], x: 50, y: 50 }, { ...nodes[1], x: 80, y: 20 }], [edges[0]], "given", "TB", 500);
    expect(pos.Customer.x).toBeGreaterThan(pos.Sale.x - 400); expect(pos.Sale.y).toBeLessThan(pos.Customer.y);
  });
});

describe("Stage", () => {
  it("renders every node as a pill at a real position, with tools, and reports clicks", () => {
    const onSelect = vi.fn();
    render(<Stage nodes={nodes} edges={edges} height={400} onSelect={onSelect} />);
    const wrappers = [...document.querySelectorAll(".react-flow__node")] as HTMLElement[];
    expect(wrappers.length).toBe(4);
    for (const el of wrappers) expect(el.style.transform).toMatch(/translate\(-?[\d.]+px, ?-?[\d.]+px\)/);
    const pills = screen.getAllByRole("button", { hidden: true }).filter(b => b.classList.contains("node"));   // hidden until React Flow measures them, which jsdom never does
    expect(pills.map(p => p.textContent)).toEqual(expect.arrayContaining(["CCustomer4", "SSale6", "PProduct", "RRegion"]));
    fireEvent.click(pills.find(p => p.textContent === "SSale6")!);
    expect(onSelect).toHaveBeenCalledWith("Sale");
    expect(screen.getByRole("button", { name: "Fit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Switch layout direction" })).toBeInTheDocument();
  });
  it("offers no relayout for a given layout", () => {
    render(<Stage nodes={nodes.slice(0, 2)} edges={[edges[0]]} height={500} layout="given" />);
    expect(screen.queryByRole("button", { name: "Switch layout direction" })).toBeNull();
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
