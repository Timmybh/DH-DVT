import type { DraftRow } from "./draft";

/** Virtual lane — khớp app/services/lanes.py: dòng chạy 4 + 5 thuộc cả lane 4 và lane 5.
 *  Dòng sở hữu (primary_line) theo `sequence`; thành viên phụ đứng sau dòng neo `extra.vanchor[line]`, chưa có neo thì suy ra theo (ngày bắt đầu, sequence). */
export const rowLines = (r: Pick<DraftRow, "primary_line" | "line_assignments">): string[] => {
  const out: string[] = [];
  for (const l of [r.primary_line, ...(r.line_assignments ?? [])]) if (l && !out.includes(String(l))) out.push(String(l));
  return out;
};

const FAR = "9999-12-31";
const keyOf = (r: DraftRow): [string, number] => [r.begin_prod_date ?? FAR, r.sequence ?? 0];
const less = (a: [string, number], b: [string, number]) => a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);

export function orderLane(line: string, members: DraftRow[]): DraftRow[] {
  const owned = members.filter((r) => r.primary_line === line).sort((a, b) => a.sequence - b.sequence);
  const sec = members.filter((r) => r.primary_line !== line);
  if (!sec.length) return owned;
  const posOf = new Map(owned.map((r, i) => [r.row_uid, i]));
  const byPos = new Map<number, DraftRow[]>();
  for (const s of sec) {
    const anchors = ((s.extra as { vanchor?: Record<string, string | null> } | undefined)?.vanchor ?? {}) as Record<string, string | null>;
    let pos = 0;
    if (line in anchors && anchors[line] === null) pos = 0;
    else if (line in anchors && posOf.has(anchors[line] as string)) pos = (posOf.get(anchors[line] as string) as number) + 1;
    else owned.forEach((o, i) => { if (less(keyOf(o), keyOf(s))) pos = i + 1; });
    byPos.set(pos, [...(byPos.get(pos) ?? []), s]);
  }
  const out: DraftRow[] = [];
  for (let p = 0; p <= owned.length; p++) {
    (byPos.get(p) ?? []).sort((a, b) => (keyOf(a)[0] < keyOf(b)[0] ? -1 : keyOf(a)[0] > keyOf(b)[0] ? 1 : a.row_uid < b.row_uid ? -1 : 1)).forEach((r) => out.push(r));
    if (p < owned.length) out.push(owned[p]);
  }
  return out;
}

export function buildLanes(rows: DraftRow[]): Map<string, DraftRow[]> {
  const members = new Map<string, DraftRow[]>();
  for (const r of rows) for (const l of rowLines(r)) (members.get(`${r.factory_code}|${l}`) ?? members.set(`${r.factory_code}|${l}`, []).get(`${r.factory_code}|${l}`)!).push(r);
  const out = new Map<string, DraftRow[]>();
  members.forEach((ms, k) => out.set(k, orderLane(k.split("|")[1], ms)));
  return out;
}
