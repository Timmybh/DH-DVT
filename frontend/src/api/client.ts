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

export interface RevenueOverview {
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

export interface ProgressOverview {
  available: boolean;
  batch?: { filename: string; imported_at: string; labor_as_of: string };
  pipeline?: { new: number; planned: number; sewn: number | null; shipped: number | null };
  total_po?: number;
  planned_qty?: number;
  risks?: { OK: number; ADVANCE: number; LATE: number; MATERIAL: number };
  risk_qty?: { OK: number; ADVANCE: number; LATE: number; MATERIAL: number };
  late_pct?: number;
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
