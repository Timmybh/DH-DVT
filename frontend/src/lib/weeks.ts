export type PlanView = "WEEK" | "MONTH" | "ALL";

const DAY = 86400000;
/** Ngày theo lịch địa phương, bỏ giờ. */
export const startOfDay = (d: Date): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d: Date, n: number): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

/** Tuần ISO 8601 (thứ Hai – Chủ nhật). */
export function isoWeek(d: Date): { year: number; week: number } {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dow = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - dow);
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return { year: t.getUTCFullYear(), week: Math.ceil(((t.getTime() - y0.getTime()) / DAY + 1) / 7) };
}

export function weekRange(anchor: Date): { start: Date; end: Date } {
  const a = startOfDay(anchor);
  const dow = (a.getDay() + 6) % 7; // 0 = thứ Hai
  const start = addDays(a, -dow);
  return { start, end: addDays(start, 6) };
}

export function monthRange(anchor: Date): { start: Date; end: Date } {
  return { start: new Date(anchor.getFullYear(), anchor.getMonth(), 1), end: new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0) };
}

export function rangeOf(view: PlanView, anchor: Date): { start: Date; end: Date } | null {
  return view === "WEEK" ? weekRange(anchor) : view === "MONTH" ? monthRange(anchor) : null;
}

/** Nhảy sang kỳ trước (-1) / kỳ sau (+1). */
export function shift(view: PlanView, anchor: Date, dir: -1 | 1): Date {
  if (view === "MONTH") return new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1);
  return addDays(anchor, 7 * dir);
}

const fmt = (d: Date) => d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });

export function periodTitle(view: PlanView, anchor: Date): { title: string; range: string } {
  if (view === "ALL") return { title: "Tất cả thời gian", range: "" };
  const r = rangeOf(view, anchor)!;
  if (view === "WEEK") {
    const w = isoWeek(r.start);
    return { title: `Tuần ${w.week}/${w.year}`, range: `${fmt(r.start)} – ${fmt(r.end)}/${r.end.getFullYear()}` };
  }
  return { title: `Tháng ${anchor.getMonth() + 1}/${anchor.getFullYear()}`, range: `${fmt(r.start)} – ${fmt(r.end)}/${r.end.getFullYear()}` };
}

const parse = (iso: string | null | undefined): Date | null => {
  if (!iso) return null;
  const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
  return isNaN(d.getTime()) ? null : d;
};

/** Dòng "thuộc" cửa sổ khi khoảng sản xuất [vào chuyền, may xong] giao với cửa sổ. Dòng chưa có ngày luôn được giữ lại để không bị ẩn âm thầm. */
export function inWindow(begin: string | null, end: string | null, win: { start: Date; end: Date } | null): boolean {
  if (!win) return true;
  const b = parse(begin), e = parse(end);
  if (!b && !e) return true;
  const s = b ?? e!, f = e ?? b!;
  return s.getTime() <= win.end.getTime() && f.getTime() >= win.start.getTime();
}
