/** Parse the first GitHub-style pipe table in a markdown string (the Stage 03 results table). */

export interface ParsedTable {
  header: string[];
  rows: string[][];
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

const SEPARATOR = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

export function parseMarkdownTable(md: string | null | undefined): ParsedTable | null {
  if (!md) return null;
  const lines = md.split(/\r?\n/);
  for (let i = 0; i + 1 < lines.length; i += 1) {
    const head = lines[i] ?? "";
    const sep = lines[i + 1] ?? "";
    if (head.includes("|") && SEPARATOR.test(sep)) {
      const header = splitRow(head);
      const rows: string[][] = [];
      for (let j = i + 2; j < lines.length; j += 1) {
        const line = lines[j] ?? "";
        if (!line.includes("|") || line.trim() === "") break;
        const cells = splitRow(line);
        while (cells.length < header.length) cells.push("");
        rows.push(cells.slice(0, header.length));
      }
      return { header, rows };
    }
  }
  return null;
}
