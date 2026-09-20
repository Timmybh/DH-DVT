interface GaugeProps {
  label: string;
  sublabel?: string;
  pct: number | null;
  /** % kỳ vọng tại thời điểm hiện tại (VD: % thời gian đã qua của tháng) — dùng để tô màu */
  expected?: number;
  selected?: boolean;
  onClick?: () => void;
  children?: React.ReactNode;
}

export function gaugeColor(pct: number | null, expected?: number): string {
  if (pct === null) return "#94a3b8";
  if (expected !== undefined) {
    if (pct >= expected) return "#16a34a";
    if (pct >= expected - 10) return "#f59e0b";
    return "#dc2626";
  }
  return pct >= 90 ? "#16a34a" : pct >= 60 ? "#f59e0b" : "#dc2626";
}

export default function Gauge({ label, sublabel, pct, expected, selected = false, onClick, children }: GaugeProps) {
  const ratio = Math.max(0, Math.min(1, (pct ?? 0) / 100));
  const angle = ratio * 180;
  const r = 40;
  const [cx, cy] = [50, 50];
  const rad = ((180 - angle) * Math.PI) / 180;
  const ex = cx - r * Math.cos(rad);
  const ey = cy - r * Math.sin(rad);
  const color = gaugeColor(pct, expected);

  const expRad = expected !== undefined ? ((180 - Math.min(100, expected) * 1.8) * Math.PI) / 180 : null;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full flex-col items-center rounded-xl border bg-white p-3 text-left hover:border-brand hover:shadow-sm ${
        selected ? "border-brand ring-2 ring-brand" : "border-slate-200"
      }`}
    >
      <p className="w-full text-center text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      {sublabel && <p className="w-full text-center text-[11px] text-slate-400">{sublabel}</p>}
      <svg viewBox="0 0 100 58" className="mt-1 w-full max-w-[220px]">
        <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="#e2e8f0" strokeWidth="9" strokeLinecap="round" />
        {pct !== null && ratio > 0 && (
          <path d={`M 10 50 A 40 40 0 0 1 ${ex} ${ey}`} fill="none" stroke={color} strokeWidth="9" strokeLinecap="round" />
        )}
        {expRad !== null && (
          <line
            x1={cx - (r - 6) * Math.cos(expRad)}
            y1={cy - (r - 6) * Math.sin(expRad)}
            x2={cx - (r + 6) * Math.cos(expRad)}
            y2={cy - (r + 6) * Math.sin(expRad)}
            stroke="#334155"
            strokeWidth="1.2"
          />
        )}
        <text x="50" y="49" textAnchor="middle" fontSize="15" fontWeight="700" fill="#0f172a">
          {pct === null ? "—" : `${pct.toFixed(1)}%`}
        </text>
      </svg>
      {children}
    </button>
  );
}
