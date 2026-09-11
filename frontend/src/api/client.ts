import axios from "axios";

export const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("dhdvt_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export interface IndicatorOut {
  indicator_key: string;
  label: string;
  status: "GREEN" | "RED";
  value: number | null;
  threshold: number | null;
  note: string;
}

export interface FactoryPlanSeries {
  factory_code: string;
  factory_name: string;
  dates: string[];
  plan: number[];
  actual: number[];
  completion_pct: number[];
}

export interface GaugeOut {
  gauge_slot: number;
  label: string;
  unit: string;
  value: number;
  target: number | null;
}

export interface IssueOut {
  id: number;
  factory_name: string | null;
  report_date: string;
  title: string;
  description: string;
  severity: string;
  status: string;
}

export interface KpiConfigOut {
  id: number;
  key: string;
  label: string;
  unit: string;
  target_value: number | null;
  warning_threshold_pct: number;
  gauge_slot: number | null;
  display_order: number;
  is_active: boolean;
}

export interface UserOut {
  id: number;
  full_name: string;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
}

export interface ImportJobOut {
  id: number;
  job_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  rows_imported: number;
  rows_skipped: number;
  error_message: string;
  triggered_by: string;
}

export interface ImportJobConfigOut {
  is_enabled: boolean;
  scheduled_time: string;
  timezone: string;
  last_run_at: string | null;
}
