import { PlanRowDto, RowRef, UnplannedDto } from "../api/client";

export type ColKind = "text" | "num" | "date";

export interface Col<T> {
  key: string;
  label: string;
  w: number;
  kind: ColKind;
  digits?: number;
  frozen?: boolean;
  get: (r: T) => string | number | null | undefined;
}

const ref = (r: { ref?: RowRef }): RowRef => r.ref ?? {};

/** Cột lưới Planned — theo thứ tự trong file Excel kế hoạch SX. */
export const PLANNED_COLS: Col<PlanRowDto>[] = [
  { key: "line", label: "Line", w: 60, kind: "text", frozen: true, get: (r) => r.line_raw || r.primary_line },
  { key: "po", label: "PO", w: 112, kind: "text", frozen: true, get: (r) => r.po_number },
  { key: "style", label: "Style/CC", w: 88, kind: "text", frozen: true, get: (r) => r.style_cc },
  { key: "factory", label: "Factory", w: 74, kind: "text", get: (r) => r.factory_code },
  { key: "model", label: "Model", w: 92, kind: "text", get: (r) => r.model_code },
  { key: "description", label: "Description", w: 230, kind: "text", get: (r) => r.description },
  { key: "customer", label: "Customer", w: 110, kind: "text", get: (r) => r.customer },
  { key: "quantity", label: "Quantity", w: 84, kind: "num", get: (r) => r.quantity },
  { key: "worker", label: "Worker", w: 68, kind: "num", get: (r) => ref(r).worker },
  { key: "capacity", label: "Capacity", w: 80, kind: "num", get: (r) => r.capacity },
  { key: "total_day", label: "Total day", w: 76, kind: "num", digits: 2, get: (r) => r.total_day },
  { key: "off_days", label: "Off days", w: 70, kind: "num", digits: 3, get: (r) => r.calc?.off_days },
  { key: "fabric_ready", label: "Fabric ready", w: 88, kind: "date", get: (r) => ref(r).fabric_ready },
  { key: "acc_ready", label: "Acc ready", w: 84, kind: "date", get: (r) => ref(r).acc_ready },
  { key: "no_issue", label: "No issue", w: 92, kind: "text", get: (r) => ref(r).no_issue },
  { key: "date_issue", label: "Date issue", w: 84, kind: "date", get: (r) => ref(r).date_issue },
  { key: "working_day", label: "Working day", w: 84, kind: "num", get: (r) => ref(r).working_day },
  { key: "sot", label: "SOT", w: 60, kind: "num", get: (r) => ref(r).sot },
  { key: "total_sot", label: "Total SOT", w: 76, kind: "num", get: (r) => ref(r).total_sot },
  { key: "begin", label: "Begin prod date", w: 96, kind: "date", get: (r) => r.begin_prod_date },
  { key: "end_begin", label: "End begin date", w: 96, kind: "date", get: (r) => r.end_prod_date },
  { key: "output", label: "Output date", w: 88, kind: "date", get: (r) => ref(r).output_date },
  { key: "end_prod", label: "End prod date", w: 92, kind: "date", get: (r) => ref(r).end_p_date },
  { key: "wh_begin", label: "Begin warehouse import", w: 120, kind: "date", get: (r) => r.warehouse_date },
  { key: "wh_end", label: "End warehouse import", w: 116, kind: "date", get: (r) => ref(r).end_wh },
  { key: "chd", label: "CHD", w: 84, kind: "date", get: (r) => r.chd },
  { key: "ehd", label: "EHD/ETD", w: 84, kind: "date", get: (r) => ref(r).ehd_etd },
  { key: "ahd", label: "AHD", w: 84, kind: "date", get: (r) => ref(r).ahd },
  { key: "on_time", label: "On time", w: 84, kind: "text", get: (r) => r.calc?.on_time ?? "" },
];

/** Cột lưới Unplanned. */
export const UNPLANNED_COLS: Col<UnplannedDto>[] = [
  { key: "factory", label: "Factory", w: 128, kind: "text", frozen: true, get: (r) => (r.factory_assignment === "KNOWN" ? r.factory_code : "Chưa xác định XN") },
  { key: "po", label: "PO", w: 112, kind: "text", frozen: true, get: (r) => r.po_number },
  { key: "style", label: "Style/CC", w: 88, kind: "text", get: (r) => r.style_cc },
  { key: "model", label: "Model", w: 92, kind: "text", get: (r) => r.model_code },
  { key: "description", label: "Description", w: 230, kind: "text", get: (r) => r.description },
  { key: "customer", label: "Customer", w: 110, kind: "text", get: (r) => r.customer },
  { key: "season", label: "Season", w: 78, kind: "text", get: (r) => r.season },
  { key: "sport", label: "Sport", w: 90, kind: "text", get: (r) => r.sport },
  { key: "quantity", label: "Quantity", w: 84, kind: "num", get: (r) => r.quantity },
  { key: "worker", label: "Worker", w: 68, kind: "num", get: (r) => ref(r).worker },
  { key: "capacity", label: "Capacity", w: 80, kind: "num", get: (r) => r.capacity },
  { key: "fabric_ready", label: "Fabric ready", w: 88, kind: "date", get: (r) => ref(r).fabric_ready },
  { key: "acc_ready", label: "Acc ready", w: 84, kind: "date", get: (r) => ref(r).acc_ready },
  { key: "po_date", label: "PO date", w: 84, kind: "date", get: (r) => r.po_date },
  { key: "chd", label: "CHD", w: 84, kind: "date", get: (r) => r.chd },
  { key: "ehd", label: "EHD/ETD", w: 84, kind: "date", get: (r) => ref(r).ehd_etd },
  { key: "note", label: "Note", w: 200, kind: "text", get: (r) => r.note },
];

const dateFmt = (v: string | number | null | undefined): string => {
  if (!v) return "—";
  const d = new Date(String(v));
  return isNaN(d.getTime()) ? String(v) : d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "2-digit" });
};

export function cellText<T>(col: Col<T>, r: T): string {
  const v = col.get(r);
  if (v === null || v === undefined || v === "") return "—";
  if (col.kind === "date") return dateFmt(v);
  if (col.kind === "num" && typeof v === "number") return v.toLocaleString("vi-VN", { maximumFractionDigits: col.digits ?? 0 });
  return String(v);
}

/** Giá trị dùng để sắp xếp (ngày → chuỗi ISO, số → số, chữ → không phân biệt hoa thường). */
export function sortValue<T>(col: Col<T>, r: T): string | number {
  const v = col.get(r);
  if (v === null || v === undefined || v === "") return col.kind === "num" ? Number.NEGATIVE_INFINITY : "";
  if (col.kind === "num") return Number(v);
  return String(v).toLowerCase();
}

export const naturalCompare = (a: string, b: string): number => a.localeCompare(b, undefined, { numeric: true });
