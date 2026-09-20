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

export interface OrderKpiBucket {
  on_time: number;
  late: number;
  no_due: number;
  overdue_open: number;
}

export interface OrderKpi {
  month: string;
  has_data: boolean;
  as_of: string | null;
  sewing: OrderKpiBucket;
  fg: OrderKpiBucket;
  fg_excluded_customers: string[];
}

export interface QaSummary {
  month: string;
  has_data: boolean;
  latest_day: string | null;
  selected: string | null;
  categories: { key: string; label: string; connected: boolean; total: number | null; by_factory: { code: string; count: number | null }[] }[];
}

export interface HrOverview {
  available: boolean;
  total?: number;
  company_total?: number;
  company_teams?: number;
  as_of_text?: string;
  teams?: number;
  by_factory?: { code: string; name: string; total: number; teams?: number }[];
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
  order_kpi: OrderKpi;
  qa: QaSummary;
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
  lead_days?: number;
}

export interface PlanRowDto {
  ref?: RowRef;
  calc?: { off_days?: number | null; on_time?: string | null; sot?: number | null; total_sot?: number | null; output_date?: string | null; end_prod_date?: string | null; end_warehouse_import?: string | null }; // cột chỉ tính theo công thức (không lưu DB)
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

// ---------------------------------------------------------------- Column Configuration / Formula
export interface PlanColumnCfg {
  code: string;
  label: string;
  workbook_header: string;
  value_type: "number" | "date" | "text";
  input_type: "MANUAL" | "LIST" | "CALCULATED";
  list_source: string;
  source: string;
  is_visible: boolean;
  formula: string | null;
  formula_id: number | null;
  formula_version: number | null;
  has_draft: boolean;
  sample: number | string | null;
}

export interface CaseResult {
  kind: string;
  ok: boolean;
  expected: number | string | null;
  actual: number | string | null;
  inputs: Record<string, unknown> | null;
  prev: Record<string, unknown> | null;
  source_row: number | null;
  synthetic: boolean;
}

export interface FormulaDef {
  id: number;
  column_code: string;
  version: number;
  status: "DRAFT" | "PUBLISHED" | "RETIRED";
  expression: string;
  result_type: string;
  rounding_policy: string;
  calendar_policy: string;
  description: string;
  workbook_formula: string;
  source_document: string;
  source_sheet: string;
  source_columns: string;
  dependencies: { columns?: string[]; semantic?: string[]; functions?: string[] };
  tolerance: number;
  verification: { tested?: number; matched?: number; rate?: number; note?: string; last_run?: { cases: number; passed: number; at: string } };
  created_by: string;
  created_at: string;
  published_by: string;
  published_at: string | null;
  case_count: number;
  cases?: CaseResult[];
}

export interface ColumnExplain {
  column: { code: string; label: string; workbook_header: string; input_type: string; list_source: string; value_type: string };
  current: FormulaDef | null;
  versions: FormulaDef[];
}

// ---------------------------------------------------------------- Dashboard runtime + cấu hình (metadata)
export interface RuntimeOutputMeta {
  rule_version?: string;
  last_calculated_at?: string;
  data_freshness?: "FRESH" | "STALE" | "UNKNOWN";
  source_last_sync_at?: string | null;
  duration_ms?: number;
}

export interface RuntimeData {
  status: "OK" | "EMPTY" | "WARNING" | "ERROR" | "STALE";
  message?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload: any;
  items: unknown[];
  meta: RuntimeOutputMeta;
}

export interface DashIndicator {
  id: number;
  indicator_code: string;
  indicator_name: string;
  group_code: string;
  group_name?: string;
  description: string;
  display_type: string;
  rule_code: string;
  data_source: string;
  default_scope: "COMPANY" | "FACTORY" | "BOTH";
  drilldown_type: string;
  drilldown_target: string;
  refresh_mode: string;
  default_enabled: boolean;
  is_active: boolean;
  display_order: number;
  owner: string;
  data_freshness_requirement: string;
  config_json: Record<string, unknown>;
}

export interface RuntimeItem {
  indicator: DashIndicator;
  position: { section: string; x: number; y: number; w: number; h: number; order: number; collapsed: boolean };
  data: RuntimeData;
}

export interface RuntimeResponse {
  layout: { id: number; layout_code: string; version: number; status: string; layout_name: string; grid_columns: number } | null;
  header: {
    scope: string;
    scope_name: string;
    today: string;
    month: string;
    has_demo?: boolean;
    sync: { revenue: SyncBrief | null; plan: SyncBrief | null };
  };
  items: RuntimeItem[];
  message?: string;
}

export interface DashGroup {
  id: number;
  group_code: string;
  group_name: string;
  description: string;
  default_enabled: boolean;
  display_order: number;
  layout_mode: string;
  collapsible: boolean;
  is_active: boolean;
}

export interface DashRule {
  id: number;
  rule_code: string;
  rule_name: string;
  rule_module: string;
  rule_function: string;
  rule_version: string;
  description: string;
  input_contract: string;
  output_contract: string;
  is_active: boolean;
  registered: boolean;
  last_test: { at?: string; by?: string; status?: string; duration_ms?: number; scope?: string };
}

export interface DashLayoutItem {
  id?: number;
  indicator_code: string;
  section: string;
  grid_x: number;
  grid_y: number;
  width: number;
  height: number;
  order_no: number;
  is_visible: boolean;
  collapsed: boolean;
  config_override_json: Record<string, unknown>;
}

export interface DashLayout {
  id: number;
  layout_code: string;
  layout_name: string;
  scope_type: "COMPANY" | "FACTORY";
  scope_value: string;
  version: number;
  status: "DRAFT" | "PUBLISHED" | "RETIRED";
  is_default: boolean;
  description: string;
  created_by: string;
  created_at: string;
  published_by: string;
  published_at: string | null;
  items?: DashLayoutItem[];
}

export interface DashOptions {
  display_types: string[];
  scopes: string[];
  drilldowns: string[];
  refresh_modes: string[];
  sections: string[];
  layout_modes: string[];
  layout_scopes: string[];
  grid_columns: number;
}
