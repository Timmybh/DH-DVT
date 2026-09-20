import type { DraftRow } from "./draft";

/** Năng suất tham chiếu từ bảng năng suất chuyền (Capacity Definition). */
export interface CapDef {
  factory_code: string | null;
  line: string | null;
  style_cc: string | null;
  model_code: string | null;
  capacity_per_day: number | null;
}

const fits = (want: string | null, val: string) => !want || want === val;

/** Năng suất 1 chuyền: định nghĩa ĐÍCH DANH mã hàng (Style/CC hoặc Model) nếu có — cụ thể nhất thắng; nếu không thì BÌNH QUÂN các định nghĩa của chuyền đó. */
export function refLineCapacity(defs: CapDef[], factory: string, line: string, style: string, model: string): { value: number; basis: "STYLE" | "LINE_AVG" } | null {
  const onLine = defs.filter((d) => d.capacity_per_day && fits(d.factory_code, factory) && fits(d.line, line));
  let best: CapDef | null = null;
  let bestScore = -1;
  for (const d of onLine) {
    if (!(d.style_cc || d.model_code)) continue;
    if (!fits(d.style_cc, style) || !fits(d.model_code, model)) continue;
    const score = (d.line ? 8 : 0) + (d.style_cc ? 4 : 0) + (d.model_code ? 2 : 0) + (d.factory_code ? 1 : 0);
    if (score > bestScore) {
      best = d;
      bestScore = score;
    }
  }
  if (best) return { value: best.capacity_per_day as number, basis: "STYLE" };
  const own = onLine.filter((d) => d.line === line);
  if (!own.length) return null;
  return { value: own.reduce((s, d) => s + (d.capacity_per_day as number), 0) / own.length, basis: "LINE_AVG" };
}

/** Năng suất tham chiếu của cả dòng = tổng các chuyền dòng đó chạy (null nếu có chuyền chưa có dữ liệu). */
export function refRowCapacity(defs: CapDef[], row: Pick<DraftRow, "factory_code" | "line_assignments" | "primary_line" | "style_cc" | "model_code">): { value: number; basis: "STYLE" | "LINE_AVG" | "MIXED" } | null {
  const lines = row.line_assignments.length ? row.line_assignments : [row.primary_line];
  let sum = 0;
  const bases = new Set<string>();
  for (const l of lines) {
    const r = refLineCapacity(defs, row.factory_code, l, row.style_cc ?? "", row.model_code ?? "");
    if (!r) return null;
    sum += r.value;
    bases.add(r.basis);
  }
  return { value: sum, basis: bases.size > 1 ? "MIXED" : ([...bases][0] as "STYLE" | "LINE_AVG") };
}
