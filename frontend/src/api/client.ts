import axios from "axios";

export const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("dvt_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && !String(err.config?.url).includes("/auth/")) {
      window.dispatchEvent(new Event("dvt-unauthorized"));
    }
    return Promise.reject(err);
  },
);

export function errorMessage(err: unknown, fallback = "Có lỗi xảy ra"): string {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e.response?.data?.detail;
  if (typeof detail === "string") return detail;
  return e.message || fallback;
}

export interface AuthUser {
  username: string;
  full_name: string;
  email: string;
  role: "ADMIN" | "PLANNER" | "VIEWER";
  permissions: string[];
  must_change_password: boolean;
  security_warnings: string[];
}

export interface Tile {
  plan: number | null;
  actual: number | null;
  remaining: number | null;
  pct: number | null;
}

export interface RevenueFactory {
  code: string;
  name: string;
  month_declared: boolean;
  month_plan: number | null;
  month_actual: number | null;
  month_pct: number | null;
  year_plan: number | null;
  year_actual: number | null;
  year_pct: number | null;
}

// Chi tiết doanh thu (chỉ dùng trong drill-down): 3 gauge, biểu đồ theo ngày, bảng theo đơn vị
export interface RevenueDetailData {
  unit: string;
  month: string;
  elapsed_pct: number;
  day: (Tile & { date: string }) | null;
  month_tile: Tile;
  year_tile: Tile;
  trend: { date: string; plan: number | null; actual: number | null }[];
  by_factory: RevenueFactory[];
  has_demo: boolean;
  latest_actual_date: string | null;
  undeclared_month: string[];
}

export interface RevenueSummaryRow {
  code: string;
  label: string;
  kind: "FACTORY" | "TOTAL";
  declared: boolean;
  plan: number | null;
  actual: number | null;
  pct: number | null;
  selected: boolean;
  missing?: string[];
}

// Bản tóm tắt điều hành trên dashboard chính
export interface RevenueOverview {
  unit: string;
  month: string;
  elapsed_pct: number;
  has_demo: boolean;
  latest_actual_date: string | null;
  year: number;
  summary: RevenueSummaryRow[];
  summary_ytd: RevenueSummaryRow[];
}

export interface ProgressOverview {
  available: boolean;
  batch?: { filename: string; imported_at: string; labor_as_of: string };
  pipeline?: { new: number; new_known: number; new_unassigned: number; planned: number; sewn: number | null; shipped: number | null };
  total_po?: number;
  planned_qty?: number;
  risks?: { OK: number; ADVANCE: number; LATE: number; MATERIAL: number };
  risk_qty?: { OK: number; ADVANCE: number; LATE: number; MATERIAL: number };
  late_pct?: number;
  mapping_warnings?: number;
  by_factory?: { code: string; name: string; po: number; qty: number; ok: number; advance: number; late: number; material: number }[];
}

export interface HrOverview {
  available: boolean;
  total?: number;
  as_of_text?: string;
  teams?: number;
  by_factory?: { code: string; name: string; total: number }[];
}

export interface SyncBrief {
  id: number;
  run_code: string;
  source: string;
  status: string;
  started_at: string;
  matched: number;
  unmatched: number;
  total_records: number;
}

export interface Overview {
  scope: string;
  scope_name: string;
  month: string;
  today: string;
  revenue: RevenueOverview;
  progress: ProgressOverview;
  hr: HrOverview;
  sync: { revenue: SyncBrief | null; plan: SyncBrief | null };
}

export type Drill =
  | { kind: "sync_run"; id: number }
  | { kind: "sync_log" }
  | { kind: "revenue"; month: string }
  | { kind: "po"; risk: string };

export interface Signal {
  id: string;
  zone: "GOOD" | "WARN";
  severity: "INFO" | "WARNING" | "CRITICAL";
  title: string;
  detail: string;
  drill: Drill | null;
}

export interface SyncRun {
  id: number;
  run_code: string;
  source: string;
  trigger_type: string;
  status: "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED";
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
  total_records: number;
  matched: number;
  unmatched: number;
  ambiguous: number;
  updated_rows: number;
  trace_id: string;
  triggered_by: string;
  retry_of: number | null;
  error_message: string;
}

export interface SyncRunDetail extends SyncRun {
  summary: { objects?: { name: string; read: number; matched: number; unmatched: number; superseded?: number }[]; filename?: string; target?: string };
  item_counts: Record<string, number>;
  items: { id: number; kind: string; source_object: string; source_key: string; message: string }[];
}

export interface UserRow {
  id: number;
  full_name: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  allow_local_login: boolean;
  last_login_at: string | null;
}

// ---------------------------------------------------------------- Planning
export interface PlanTransfer {
  from: string;
  to: string;
  effective_date: string | null;
  planned_remaining_qty: number | null;
  status: string;
}

// Thông tin tham chiếu từ file Excel nguồn, chỉ để hiển thị trên lưới
export interface RowRef {
  worker?: number | null;
  ehd_etd?: string | null;
  ahd?: string | null;
  fabric_ready?: string | null;
  acc_ready?: string | null;
  no_issue?: string;
  date_issue?: string | null;
  working_day?: number;
  sot?: number;
  total_sot?: number;
  output_date?: string | null;
  end_p_date?: string | null;
  end_wh?: string | null;
  on_time?: string;
  risk?: "OK" | "ADVANCE" | "LATE" | "MATERIAL";
  risk_reason?: string;
  gap_days?: number | null;
}

export interface PlanRowDto {
  ref?: RowRef;
  row_uid: string;
  sequence: number;
  origin: "EXISTING" | "DRAFT_NEW";
  source_key: string;
  source_plan_row_id: number | null;
  factory_code: string;
  primary_line: string;
  line_raw: string;
  line_assignments: string[];
  transfer: PlanTransfer | null;
  po_number: string;
  style_cc: string;
  model_code: string;
  description: string;
  customer: string;
  sport: string;
  season: string;
  quantity: number;
  capacity: number | null;
  total_day: number | null;
  begin_prod_date: string | null;
  end_prod_date: string | null;
  warehouse_date: string | null;
  chd: string | null;
  note: string;
  extra: { overrides?: Record<string, { source: string; calculated: unknown }> };
}

export interface UnplannedDto {
  ref?: RowRef;
  returned?: boolean; // dòng đã được trả về Unplanned từ kế hoạch
  row_uid?: string;
  snapshot?: PlanRowDto;
  id: number;
  source_key: string;
  factory_code: string;
  factory_assignment: "KNOWN" | "UNASSIGNED";
  mapping_status: "OK" | "WARNING";
  mapping_note: string;
  fac_raw: string;
  po_number: string;
  style_cc: string;
  model_code: string;
  description: string;
  customer: string;
  sport: string;
  season: string;
  quantity: number;
  capacity: number | null;
  chd: string | null;
  note: string;
  po_date: string | null;
}

export interface PlanVersion {
  id: number;
  code: string;
  year: number;
  week: number;
  major: number;
  minor: number | null;
  parent_id: number | null;
  status: "COMMITTED" | "ISSUED" | "SUPERSEDED";
  note: string;
  created_by: string;
  created_at: string;
  row_count: number;
  recheck_result: "PASS" | "WARNING" | "ERROR" | "";
  recheck_trace_id: string;
  recheck_at: string | null;
  recheck_summary: { counts?: { ERROR: number; WARNING: number; rows: number }; by_rule?: Record<string, number> };
  issued_at: string | null;
  issued_by: string;
  base_version_id: number | null;
}

export interface EditSessionView {
  id: string;
  username: string;
  status: string;
  started_at: string;
  last_heartbeat: string;
  base_version_id: number | null;
  is_mine: boolean;
  timeout_seconds: number;
}

export interface RecheckIssue {
  severity: "ERROR" | "WARNING";
  row_uid: string;
  column: string;
  message: string;
  rule_code: string;
  po_number: string;
}

export interface RecheckResult {
  result: "PASS" | "WARNING" | "ERROR";
  issues: RecheckIssue[];
  counts: { ERROR: number; WARNING: number; rows: number };
  by_rule: Record<string, number>;
  trace_id: string;
  duration_ms: number;
  draft_revision: number;
  computed_rows: PlanRowDto[];
}
