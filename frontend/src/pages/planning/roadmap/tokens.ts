/** Strategic Roadmap design tokens (GPT UI spec 2026-09-28) — nguồn duy nhất cho màu category/status
 * dùng xuyên suốt module (không được đổi màu giữa các màn hình). CSS var định nghĩa ở index.css (.roadmap-shell). */
import { Banknote, BarChart3, Cpu, ShieldCheck, Users2, type LucideIcon } from "lucide-react";

export type CategoryToken = "Doanh số" | "Chất lượng" | "OPEX" | "Digital Transformation" | "HR";

export const CATEGORY_ICON: Record<string, LucideIcon> = {
  "Doanh số": BarChart3,
  "Chất lượng": ShieldCheck,
  OPEX: Banknote,
  "Digital Transformation": Cpu,
  HR: Users2,
};

export const CATEGORY_VARS: Record<string, { fg: string; bg: string }> = {
  "Doanh số": { fg: "var(--rm-cat-revenue)", bg: "var(--rm-cat-revenue-bg)" },
  "Chất lượng": { fg: "var(--rm-cat-quality)", bg: "var(--rm-cat-quality-bg)" },
  OPEX: { fg: "var(--rm-cat-opex)", bg: "var(--rm-cat-opex-bg)" },
  "Digital Transformation": { fg: "var(--rm-cat-dx)", bg: "var(--rm-cat-dx-bg)" },
  HR: { fg: "var(--rm-cat-hr)", bg: "var(--rm-cat-hr-bg)" },
};

export function categoryVars(name: string | null | undefined) {
  return (name && CATEGORY_VARS[name]) || { fg: "var(--rm-cat-none)", bg: "var(--rm-cat-none-bg)" };
}

export function categoryIcon(name: string | null | undefined): LucideIcon {
  return (name && CATEGORY_ICON[name]) || Cpu;
}

export type StatusToken = "ON_TRACK" | "AT_RISK" | "BEHIND";

/** Nhãn hiển thị: ON_TRACK tách "Đang thực hiện"/"Đã hoàn thành" theo progress (thuần trình bày, KHÔNG thêm status backend mới). */
export function statusLabel(status: StatusToken, progressPercent: number | null): string {
  if (status === "ON_TRACK") return progressPercent !== null && progressPercent >= 100 ? "Đã hoàn thành" : "Đang thực hiện";
  if (status === "AT_RISK") return "Có rủi ro";
  return "Bị chậm";
}
export const STATUS_VARS: Record<StatusToken, { fg: string; bg: string }> = {
  ON_TRACK: { fg: "var(--rm-status-ontrack)", bg: "var(--rm-status-ontrack-bg)" },
  AT_RISK: { fg: "var(--rm-status-risk)", bg: "var(--rm-status-risk-bg)" },
  BEHIND: { fg: "var(--rm-status-behind)", bg: "var(--rm-status-behind-bg)" },
};
export const STATUS_LEGEND: { status: StatusToken; label: string }[] = [
  { status: "ON_TRACK", label: "Đang thực hiện / Đã hoàn thành" },
  { status: "AT_RISK", label: "Có rủi ro" },
  { status: "BEHIND", label: "Bị chậm" },
];
