import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "..", "src", "app", "globals.css"), "utf-8");

function token(name: string): string {
  const m = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
  if (!m) throw new Error(`missing css variable --${name}`);
  return m[1]!;
}
function luminance(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

describe("light palette meets WCAG AA for text", () => {
  const pairs: [string, string][] = [
    ["text", "bg"], ["text", "surface"], ["text-2", "bg"], ["text-2", "surface"], ["text-2", "surface-2"],
    ["link", "bg"], ["link", "surface"], ["link", "accent-soft"],
    ["danger", "danger-soft"], ["warn", "warn-soft"], ["ok", "ok-soft"],
  ];
  it.each(pairs)("--%s on --%s is at least 4.5:1", (fg, bg) => {
    expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(4.5);
  });
  it("white text on the link blue (primary button) is at least 4.5:1", () => {
    expect(contrast("#ffffff", token("link"))).toBeGreaterThanOrEqual(4.5);
  });
  it("the accent used for graphics and focus rings is at least 3:1 on white", () => {
    expect(contrast(token("accent"), token("bg"))).toBeGreaterThanOrEqual(3);
  });
  it("the page is light only: no dark-mode media query", () => {
    expect(css).not.toMatch(/prefers-color-scheme:\s*dark/);
    expect(css).toMatch(/color-scheme:\s*light/);
  });
});
