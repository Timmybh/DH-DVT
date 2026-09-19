const nf0 = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 });

export const num = (v: number | null | undefined, digits = 0): string =>
  v === null || v === undefined ? "—" : (digits ? nf1 : nf0).format(v);

export const pct = (v: number | null | undefined): string => (v === null || v === undefined ? "—" : `${nf1.format(v)}%`);

export const dateVi = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("vi-VN");
};

export const dateTimeVi = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("vi-VN", { hour12: false });
};

export const duration = (ms: number): string => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

export const SOURCE_LABEL: Record<string, string> = {
  EGMF_REVENUE: "eGMF — Doanh thu XN",
  PLAN_EXCEL: "File Excel kế hoạch SX",
};

export const ROLE_LABEL: Record<string, string> = {
  ADMIN: "Quản trị",
  PLANNER: "Lập kế hoạch",
  VIEWER: "Xem",
};
