import { describe, expect, it } from "vitest";
import { mergeNeighbourhood, mergeSample, type ExploreGraph } from "@/screens/Explore";
import type { EntityDetail } from "@/api";

const entity = (id: string, out: [string, string][], inc: [string, string][] = []): EntityDetail => ({
  id, label: id, type: "Customer", iri: id, attrs: [],
  out: Object.entries(out.reduce<Record<string, string[]>>((a, [p, t]) => { (a[p] ||= []).push(t); return a; }, {})).map(([pred, ts]) => ({ pred, targets: ts.map(t => ({ id: t, label: t, type: "" })) })),
  inc: Object.entries(inc.reduce<Record<string, string[]>>((a, [p, t]) => { (a[p] ||= []).push(t); return a; }, {})).map(([pred, ts]) => ({ pred, count: String(ts.length), targets: ts.map(t => ({ id: t, label: t, type: "" })) })),
  far: [],
});

describe("Explore graph expansion", () => {
  it("grows the graph hop by hop without duplicating nodes or edges, refining types as they become known", () => {
    let g: ExploreGraph = { nodes: {}, edges: [] };
    g = mergeNeighbourhood(g, entity("A", [["knows", "B"], ["knows", "C"]], [["likes", "D"]]));
    expect(Object.keys(g.nodes).sort()).toEqual(["A", "B", "C", "D"]);
    expect(g.edges).toEqual([{ from: "A", to: "B", label: "knows" }, { from: "A", to: "C", label: "knows" }, { from: "D", to: "A", label: "likes" }]);
    g = mergeNeighbourhood(g, entity("B", [["knows", "E"]], [["knows", "A"]]));   // B's own view repeats A→B
    expect(Object.keys(g.nodes).sort()).toEqual(["A", "B", "C", "D", "E"]);
    expect(g.edges.length).toBe(4);
    expect(g.nodes.B.type).toBe("Customer");   // known once B itself was opened
  });
});


describe("Explore overview", () => {
  it("lays the sample on the canvas and later neighbourhoods refine it without duplicates", () => {
    let g = mergeSample({ nodes: {}, edges: [] }, { nodes: [{ id: "A", label: "A", type: "Customer" }, { id: "B", label: "B", type: "" }], edges: [{ from: "A", to: "B", label: "knows" }] });
    expect(Object.keys(g.nodes)).toEqual(["A", "B"]);
    g = mergeNeighbourhood(g, entity("B", [["knows", "C"]], [["knows", "A"]]));
    expect(g.edges.length).toBe(2);
    expect(g.nodes.B.type).toBe("Customer");
  });
});
