"use client";
import { useMemo, useState } from "react";
import { capGraph, layoutGraph, NODE_CAP, type PositionedNode } from "@/lib/graph";
import { formatInr } from "@/lib/format";
import type { Case } from "@/lib/types";

const EDGE_COLOR = "#8aa0bf";

export function ForceGraph({ ring, cap = NODE_CAP }: { ring: Pick<Case, "members" | "edges" | "edges_available" | "edges_truncated" | "members_truncated">; cap?: number }) {
  const capped = useMemo(() => capGraph(ring, cap), [ring, cap]);
  const layout = useMemo(() => layoutGraph(capped), [capped]);
  const [selected, setSelected] = useState<string | null>(null);
  const sel = layout.nodes.find((n) => n.id === selected) ?? null;

  if (!ring.edges_available) {
    return (
      <div className="state" role="status">
        <h3>No transfer graph in this bundle</h3>
        <p className="muted">The bundle was exported without transfer edges (events file missing or --no-edges). The member accounts are listed below.</p>
      </div>
    );
  }
  if (layout.nodes.length === 0 || layout.edges.length === 0) {
    return (
      <div className="state" role="status">
        <h3>No transfers to draw</h3>
        <p className="muted">This ring has no account-to-account edges in the bundle.</p>
      </div>
    );
  }

  const maxTotal = layout.edges.reduce((m, e) => Math.max(m, e.total_inr), 1);
  const neighbours = sel ? layout.edges.filter((e) => e.src === sel.id || e.dst === sel.id) : [];

  return (
    <div>
      <p className="small muted" data-testid="graph-summary">
        Showing {layout.nodes.length} of {capped.totalNodes} accounts and {layout.edges.length} of {capped.totalEdges} transfer links.
        {capped.capped && ` Capped at ${cap} accounts: the ones with the largest transfer volume are kept.`}
        {ring.edges_truncated && " The bundle itself holds only part of this ring’s transfers."}
        {ring.members_truncated && " The member list is also truncated in the bundle."}
      </p>
      <div className="layout-2">
        <div className="graph-box">
          <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={`Transfer graph of ${layout.nodes.length} accounts`} data-testid="graph-svg">
            <defs>
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill={EDGE_COLOR} />
              </marker>
            </defs>
            {layout.edges.map((e) => (
              <line
                key={`${e.src}>${e.dst}`}
                x1={e.source.x}
                y1={e.source.y}
                x2={e.target.x}
                y2={e.target.y}
                stroke={EDGE_COLOR}
                strokeWidth={0.8 + 2.4 * Math.sqrt(e.total_inr / maxTotal)}
                strokeOpacity={sel && e.src !== sel.id && e.dst !== sel.id ? 0.15 : 0.7}
                markerEnd="url(#arrow)"
                data-testid="graph-edge"
              >
                <title>{`${e.src} → ${e.dst}: ${e.n_transfers} transfer(s), ${formatInr(e.total_inr)}`}</title>
              </line>
            ))}
            {layout.nodes.map((n) => (
              <circle
                key={n.id}
                cx={n.x}
                cy={n.y}
                r={n.r}
                fill={n.isMember ? "#2a78d6" : "#ffffff"}
                stroke="#0c2451"
                strokeWidth={n.id === selected ? 3 : 1.2}
                tabIndex={0}
                role="button"
                aria-label={`Account ${n.id}, ${n.degree} links, ${formatInr(n.strength)} moved`}
                onClick={() => setSelected(n.id === selected ? null : n.id)}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter" || ev.key === " ") {
                    ev.preventDefault();
                    setSelected(n.id === selected ? null : n.id);
                  }
                }}
                data-testid="graph-node"
              >
                <title>{`${n.id}: ${formatInr(n.strength)} moved`}</title>
              </circle>
            ))}
          </svg>
        </div>
        <aside className="card soft" aria-live="polite">
          <h3>Account detail</h3>
          {sel ? <AccountDetail node={sel} links={neighbours.length} /> : <p className="muted small">Select an account (click, or Enter on a focused node) to see its flows. Arrows point from sender to receiver; line width follows rupees moved.</p>}
        </aside>
      </div>
    </div>
  );
}

function AccountDetail({ node, links }: { node: PositionedNode; links: number }) {
  return (
    <dl className="small" style={{ margin: 0 }}>
      <dt className="muted">Account</dt>
      <dd className="mono" style={{ margin: "0 0 8px" }}>{node.id}</dd>
      <dt className="muted">Sent</dt>
      <dd style={{ margin: "0 0 8px" }}>{formatInr(node.outInr)}</dd>
      <dt className="muted">Received</dt>
      <dd style={{ margin: "0 0 8px" }}>{formatInr(node.inInr)}</dd>
      <dt className="muted">Links in view</dt>
      <dd style={{ margin: 0 }}>{links}</dd>
    </dl>
  );
}
