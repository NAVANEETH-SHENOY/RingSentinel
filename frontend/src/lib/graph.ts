/** Case-graph preparation: build nodes from a case, apply the deterministic node cap, lay out.
 *
 *  Cap rule (plan section 9, risk R6): keep the `cap` accounts with the largest total transfer
 *  volume (sum of total_inr over all incident edges); ties are broken by account id ascending.
 *  Edges are kept only when both ends are kept. The rule depends on nothing but the case content,
 *  so the same case always shows the same graph.
 */

import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";
import type { Case, Edge } from "./types";

export const NODE_CAP = 500;
export const LAYOUT_SIZE = { width: 900, height: 620 };
const LAYOUT_TICKS = 300;
const MIN_VIEW = { width: 420, height: 300 };

export interface GraphNode {
  id: string;
  /** Total INR over incident edges (in + out). */
  strength: number;
  inInr: number;
  outInr: number;
  degree: number;
  isMember: boolean;
}

export interface CappedGraph {
  nodes: GraphNode[];
  edges: Edge[];
  totalNodes: number;
  totalEdges: number;
  droppedNodes: number;
  droppedEdges: number;
  capped: boolean;
}

export function buildNodes(c: Pick<Case, "members" | "edges">): GraphNode[] {
  const byId = new Map<string, GraphNode>();
  const get = (id: string, isMember: boolean) => {
    let n = byId.get(id);
    if (!n) {
      n = { id, strength: 0, inInr: 0, outInr: 0, degree: 0, isMember };
      byId.set(id, n);
    } else if (isMember) {
      n.isMember = true;
    }
    return n;
  };
  const members = new Set(c.members);
  for (const m of c.members) get(m, true);
  for (const e of c.edges) {
    const a = get(e.src, members.has(e.src));
    const b = get(e.dst, members.has(e.dst));
    if (e.src === e.dst) {
      a.strength += e.total_inr;
      continue;
    }
    a.outInr += e.total_inr;
    b.inInr += e.total_inr;
    a.strength += e.total_inr;
    b.strength += e.total_inr;
    a.degree += 1;
    b.degree += 1;
  }
  return [...byId.values()];
}

export function capGraph(c: Pick<Case, "members" | "edges">, cap = NODE_CAP): CappedGraph {
  if (!Number.isInteger(cap) || cap < 1) throw new RangeError("cap must be a positive integer");
  const all = buildNodes(c);
  const ranked = [...all].sort((a, b) => b.strength - a.strength || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const kept = ranked.slice(0, cap);
  const keptIds = new Set(kept.map((n) => n.id));
  const edges = c.edges.filter((e) => e.src !== e.dst && keptIds.has(e.src) && keptIds.has(e.dst));
  const drawableTotal = c.edges.filter((e) => e.src !== e.dst).length;
  // Stable presentation order (by id) so layout seeds do not depend on ranking ties.
  kept.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return {
    nodes: kept,
    edges,
    totalNodes: all.length,
    totalEdges: drawableTotal,
    droppedNodes: all.length - kept.length,
    droppedEdges: drawableTotal - edges.length,
    capped: all.length > kept.length,
  };
}

export interface PositionedNode extends GraphNode {
  x: number;
  y: number;
  r: number;
}

export interface Layout {
  nodes: PositionedNode[];
  edges: (Edge & { source: PositionedNode; target: PositionedNode })[];
  width: number;
  height: number;
}

export function nodeRadius(strength: number, maxStrength: number): number {
  if (maxStrength <= 0) return 5;
  return 4 + 8 * Math.sqrt(Math.max(0, strength) / maxStrength);
}

/** Force layout run to completion synchronously. d3-force starts from a fixed phyllotaxis
 *  arrangement and uses its own seeded generator, so the same input gives the same positions. */
export function layoutGraph(g: Pick<CappedGraph, "nodes" | "edges">, base = LAYOUT_SIZE): Layout {
  // Bigger graphs get a bigger canvas (viewBox only; the SVG still scales to its container).
  const factor = Math.max(1, Math.sqrt(g.nodes.length / 80));
  const size = { width: Math.round(base.width * factor), height: Math.round(base.height * factor) };
  const maxStrength = g.nodes.reduce((m, n) => Math.max(m, n.strength), 0);
  const nodes: PositionedNode[] = g.nodes.map((n) => ({ ...n, x: 0, y: 0, r: nodeRadius(n.strength, maxStrength) }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = g.edges.map((e) => ({ source: e.src, target: e.dst }));
  const sim = forceSimulation(nodes)
    .force("link", forceLink<PositionedNode, { source: string; target: string }>(links).id((n) => n.id).distance(46).strength(0.6))
    .force("charge", forceManyBody().strength(-70))
    .force("collide", forceCollide<PositionedNode>().radius((n) => n.r + 2))
    .force("center", forceCenter(size.width / 2, size.height / 2))
    .force("x", forceX(size.width / 2).strength(0.04))
    .force("y", forceY(size.height / 2).strength(0.04))
    .stop();
  for (let i = 0; i < LAYOUT_TICKS; i += 1) sim.tick();
  // Fit the viewBox to the drawing (with padding and a minimum size) so small rings are not
  // lost in a big empty canvas and nothing is clamped against an edge.
  const pad = 24;
  const bbox = nodes.length
    ? {
        x0: Math.min(...nodes.map((n) => n.x - n.r)),
        y0: Math.min(...nodes.map((n) => n.y - n.r)),
        x1: Math.max(...nodes.map((n) => n.x + n.r)),
        y1: Math.max(...nodes.map((n) => n.y + n.r)),
      }
    : { x0: 0, y0: 0, x1: 1, y1: 1 };
  const width = Math.max(MIN_VIEW.width, Math.ceil(bbox.x1 - bbox.x0 + 2 * pad));
  const height = Math.max(MIN_VIEW.height, Math.ceil(bbox.y1 - bbox.y0 + 2 * pad));
  const dx = (width - (bbox.x1 - bbox.x0)) / 2 - bbox.x0;
  const dy = (height - (bbox.y1 - bbox.y0)) / 2 - bbox.y0;
  for (const n of nodes) {
    n.x += dx;
    n.y += dy;
  }
  const edges = g.edges.flatMap((e) => {
    const source = byId.get(e.src);
    const target = byId.get(e.dst);
    return source && target ? [{ ...e, source, target }] : [];
  });
  return { nodes, edges, width, height };
}
