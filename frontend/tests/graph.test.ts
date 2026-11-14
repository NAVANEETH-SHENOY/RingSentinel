import { describe, expect, it } from "vitest";
import { buildNodes, capGraph, layoutGraph, NODE_CAP } from "@/lib/graph";
import type { Edge } from "@/lib/types";
import { demoDoc } from "./helpers";

const edge = (src: string, dst: string, total: number): Edge => ({
  src, dst, n_transfers: 1, total_inr: total, first_ts: "2022-09-01T00:00:00", last_ts: "2022-09-01T00:00:00",
});

function bigCase(n: number) {
  const edges: Edge[] = [];
  const members: string[] = [];
  for (let i = 0; i < n; i += 1) {
    members.push(`A${String(i).padStart(5, "0")}`);
    // a path graph plus some chords; volume grows with i so ranking is not trivial
    if (i > 0) edges.push(edge(`A${String(i - 1).padStart(5, "0")}`, `A${String(i).padStart(5, "0")}`, 100 + (i % 97) * 10));
  }
  return { members, edges };
}

describe("buildNodes", () => {
  it("sums in/out volume and counts links", () => {
    const nodes = buildNodes({ members: ["a", "b", "c"], edges: [edge("a", "b", 100), edge("b", "c", 40), edge("a", "c", 10)] });
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    expect(byId.a).toMatchObject({ outInr: 110, inInr: 0, strength: 110, degree: 2 });
    expect(byId.b).toMatchObject({ outInr: 40, inInr: 100, strength: 140, degree: 2 });
    expect(byId.c).toMatchObject({ outInr: 0, inInr: 50, strength: 50, degree: 2 });
  });

  it("keeps member accounts that have no edges, and ignores self links for degree", () => {
    const nodes = buildNodes({ members: ["a", "lonely"], edges: [edge("a", "a", 5)] });
    expect(nodes.map((n) => n.id).sort()).toEqual(["a", "lonely"]);
    expect(nodes.find((n) => n.id === "a")?.degree).toBe(0);
  });
});

describe("capGraph (the node cap)", () => {
  it("does not touch a graph under the cap", () => {
    const g = capGraph({ members: ["a", "b"], edges: [edge("a", "b", 1)] });
    expect(g.capped).toBe(false);
    expect(g.nodes).toHaveLength(2);
    expect(g.droppedNodes).toBe(0);
  });

  it("never returns more than the cap, and the default cap is 500", () => {
    expect(NODE_CAP).toBe(500);
    const g = capGraph(bigCase(1500));
    expect(g.nodes).toHaveLength(500);
    expect(g.totalNodes).toBe(1500);
    expect(g.droppedNodes).toBe(1000);
    expect(g.capped).toBe(true);
  });

  it("keeps only edges whose both ends survive", () => {
    const g = capGraph(bigCase(1500));
    const ids = new Set(g.nodes.map((n) => n.id));
    expect(g.edges.length).toBeGreaterThan(0);
    for (const e of g.edges) {
      expect(ids.has(e.src) && ids.has(e.dst)).toBe(true);
    }
    expect(g.edges.length + g.droppedEdges).toBe(g.totalEdges);
  });

  it("keeps the highest-volume accounts, breaking ties by id", () => {
    const g = capGraph({ members: ["a", "b", "c", "d"], edges: [edge("a", "b", 100), edge("c", "d", 100)] }, 3);
    // all four have strength 100; the id tie-break keeps a, b, c
    expect(g.nodes.map((n) => n.id)).toEqual(["a", "b", "c"]);
    const big = capGraph({ members: ["x", "y", "z"], edges: [edge("x", "y", 10), edge("y", "z", 500)] }, 2);
    expect(big.nodes.map((n) => n.id)).toEqual(["y", "z"]);
  });

  it("is deterministic and independent of input order", () => {
    const c = bigCase(900);
    const shuffled = { members: [...c.members].reverse(), edges: [...c.edges].reverse() };
    const a = capGraph(c);
    const b = capGraph(shuffled);
    expect(b.nodes.map((n) => n.id)).toEqual(a.nodes.map((n) => n.id));
    expect(b.edges.map((e) => `${e.src}>${e.dst}`).sort()).toEqual(a.edges.map((e) => `${e.src}>${e.dst}`).sort());
  });

  it("rejects a nonsensical cap", () => {
    expect(() => capGraph({ members: [], edges: [] }, 0)).toThrow(RangeError);
    expect(() => capGraph({ members: [], edges: [] }, 1.5)).toThrow(RangeError);
  });

  it("holds on the demo bundle's oversized ring (more than 500 accounts)", () => {
    const cases = Object.values(demoDoc("cases.json").cases) as { oversized: boolean; members: string[]; edges: Edge[] }[];
    const big = cases.find((c) => c.oversized);
    expect(big).toBeDefined();
    const g = capGraph(big!);
    expect(g.totalNodes).toBeGreaterThan(500);
    expect(g.nodes).toHaveLength(500);
  });
});

describe("layoutGraph", () => {
  it("is deterministic and keeps every node inside the canvas", () => {
    const g = capGraph(bigCase(120));
    const a = layoutGraph(g);
    const b = layoutGraph(g);
    expect(b.nodes.map((n) => [n.x, n.y])).toEqual(a.nodes.map((n) => [n.x, n.y]));
    for (const n of a.nodes) {
      expect(Number.isFinite(n.x) && Number.isFinite(n.y)).toBe(true);
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(a.width);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeLessThanOrEqual(a.height);
    }
    expect(a.edges.every((e) => e.source && e.target)).toBe(true);
  });
});

describe("layout fits its content", () => {
  it("uses a small view for a small ring and never places a node outside it", () => {
    const small = layoutGraph(capGraph({ members: ["a", "b", "c"], edges: [edge("a", "b", 5), edge("b", "c", 5)] }));
    expect(small.width).toBeLessThan(600);
    for (const n of small.nodes) {
      expect(n.x - n.r).toBeGreaterThanOrEqual(0);
      expect(n.x + n.r).toBeLessThanOrEqual(small.width);
      expect(n.y - n.r).toBeGreaterThanOrEqual(0);
      expect(n.y + n.r).toBeLessThanOrEqual(small.height);
    }
  });
});
