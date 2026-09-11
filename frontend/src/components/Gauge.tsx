interface GaugeProps {
  label: string;
  value: number;
  target: number | null;
  unit: string;
}

export default function Gauge({ label, value, target, unit }: GaugeProps) {
  const max = target && target > 0 ? target : 100;
  const pct = Math.max(0, Math.min(1, value / max));
  const angle = pct * 180;

  const radius = 40;
  const cx = 50;
  const cy = 50;
  const toXY = (deg: number) => {
    const rad = ((180 - deg) * Math.PI) / 180;
    return [cx - radius * Math.cos(rad), cy - radius * Math.sin(rad)];
  };
  const [ex, ey] = toXY(angle);

  const color = pct >= 0.9 ? "#16a34a" : pct >= 0.6 ? "#f59e0b" : "#dc2626";

  return (
    <div className="flex flex-col items-center rounded-xl border border-slate-200 bg-white p-3">
      <svg viewBox="0 0 100 55" className="w-full">
        <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="#e2e8f0" strokeWidth="8" strokeLinecap="round" />
        <path
          d={`M 10 50 A 40 40 0 0 1 ${ex} ${ey}`}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
        />
        <text x="50" y="48" textAnchor="middle" fontSize="14" fontWeight="700" fill="#1e293b">
          {value}
          {unit}
        </text>
      </svg>
      <p className="mt-1 truncate text-center text-xs font-medium text-slate-500" title={label}>
        {label}
      </p>
    </div>
  );
}
