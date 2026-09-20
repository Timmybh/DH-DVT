/** Bảng màu trung tâm — nguồn duy nhất cho màu trạng thái / biểu đồ. Giá trị thật lấy từ API /theme (Quản trị → Giao diện); mặc định trùng backend. */
export interface ThemeTokens {
  brand: string;
  status: { ok: string; warn: string; bad: string; info: string; neutral: string };
  series: string[];
}

export const DEFAULT_TOKENS: ThemeTokens = {
  brand: "#4f46e5",
  status: { ok: "#16a34a", warn: "#f59e0b", bad: "#dc2626", info: "#38bdf8", neutral: "#94a3b8" },
  series: ["#6366f1", "#0ea5e9", "#f59e0b", "#a78bfa"],
};

/** Đối tượng có thể thay đổi tại chỗ; component gọi useTheme() để render lại khi token đổi. */
export const palette: ThemeTokens = JSON.parse(JSON.stringify(DEFAULT_TOKENS));

const rgb = (hex: string): string => `${parseInt(hex.slice(1, 3), 16)} ${parseInt(hex.slice(3, 5), 16)} ${parseInt(hex.slice(5, 7), 16)}`;

export function applyTokens(t: ThemeTokens): void {
  palette.brand = t.brand;
  palette.status = { ...t.status };
  palette.series = [...t.series];
  const root = document.documentElement.style;
  root.setProperty("--brand-rgb", rgb(t.brand));
  root.setProperty("--st-ok", t.status.ok);
  root.setProperty("--st-warn", t.status.warn);
  root.setProperty("--st-bad", t.status.bad);
  root.setProperty("--st-info", t.status.info);
  root.setProperty("--st-neutral", t.status.neutral);
}

/** Màu theo xí nghiệp lấy từ dải màu biểu đồ. */
export const factoryColor = (code: string): string => palette.series[(Math.max(1, parseInt(code.replace(/\D/g, ""), 10) || 1) - 1) % palette.series.length];
