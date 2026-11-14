"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { OriginChip } from "./StatusChip";
import { SourceProvider, useSource } from "@/lib/SourceContext";
import type { Source } from "@/lib/source";
import type { Health, Meta, Origin } from "@/lib/types";
import { shortHash } from "@/lib/format";

const NAV = [
  { href: "/", label: "Review queue" },
  { href: "/metrics/", label: "Metrics" },
  { href: "/audit/", label: "Audit log" },
  { href: "/replay/", label: "Replay" },
];

function isActive(pathname: string, href: string): boolean {
  const norm = (p: string) => (p.length > 1 ? p.replace(/\/+$/, "") : p);
  if (href === "/") return norm(pathname) === "/" || norm(pathname) === "/case";
  return norm(pathname) === norm(href);
}

interface ShellInfo {
  meta: Meta | null;
  origin: Origin | null;
  health: Health | null;
  done: boolean;
}

function StatusBar() {
  const source = useSource();
  const [info, setInfo] = useState<ShellInfo>({ meta: null, origin: null, health: null, done: false });

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([source.meta(), source.health()]).then(([m, h]) => {
      if (cancelled) return;
      const meta = m.status === "fulfilled" ? m.value : null;
      const health = h.status === "fulfilled" ? h.value : null;
      setInfo({ meta: meta?.data ?? null, origin: health ? "api" : (meta?.origin ?? null), health, done: true });
    });
    return () => {
      cancelled = true;
    };
  }, [source]);

  const { meta, origin, health } = info;
  const mismatch = meta !== null && health !== null && meta.bundle_id !== health.bundle_id;
  const isDemo = meta?.dataset_variant.toUpperCase().startsWith("DEMO") === true;
  const frozen = meta?.evaluation_frozen ?? false;
  return (
    <>
      {isDemo && (
        <div className="banner demo" role="note">
          <strong>Demo data.</strong> Every number, account and ring here is invented to develop the interface. None of it is a result.
        </div>
      )}
      {meta && !isDemo && !frozen && (
        <div className="banner info" role="note">
          <strong>Numbers not frozen.</strong> This bundle was exported before the Stage 03 evaluation was frozen; treat figures as provisional.
        </div>
      )}
      {mismatch && (
        <div className="banner demo" role="alert">
          <strong>Snapshot out of date.</strong> The saved snapshot is not the bundle the live API serves. Pages use the API while it answers and fall back to the older snapshot if it does not. Run scripts\sync_frontend_snapshots.py.
        </div>
      )}
      <div className="shell-inner" style={{ paddingTop: 6, paddingBottom: 6 }} aria-label="Data source">
        {origin ? <OriginChip origin={isDemo ? "demo" : origin} /> : <span className="chip">checking source…</span>}
        {meta && (
          <span className="small muted">
            {meta.dataset_variant} · {meta.detector} on {meta.split} · bundle <span className="mono">{shortHash(meta.bundle_id)}</span>
          </span>
        )}
        {source.config.apiBase && !health && info.done && (
          <span className="small muted">Backend unreachable: using saved snapshot.</span>
        )}
      </div>
    </>
  );
}

export function AppShell({ children, source }: { children: ReactNode; source?: Source }) {
  const pathname = usePathname() ?? "/";
  return (
    <SourceProvider source={source}>
      <header className="shell-header">
        <div className="shell-inner">
          <Link href="/" className="brand">
            Ring<span>Sentinel</span>
          </Link>
          <nav className="nav" aria-label="Main">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} aria-current={isActive(pathname, n.href) ? "page" : undefined}>
                {n.label}
              </Link>
            ))}
          </nav>
          <span className="small muted">Defense-only · a human decides</span>
        </div>
        <StatusBar />
      </header>
      <main>{children}</main>
    </SourceProvider>
  );
}
