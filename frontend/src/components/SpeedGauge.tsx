import { useTheme } from "../theme/ThemeContext";

interface Props {
  label: string;
  pct: number | null;
}

const CX = 60;
const CY = 56;
const R = 38; // bán kính đường giữa của dải màu
const W = 17; // độ dày dải màu

const point = (pct: number, r: number): [number, number] => {
  const a = Math.PI * (1 - pct / 100);
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)];
};
const arc = (from: number, to: number) => {
  const [x1, y1] = point(from, R);
  const [x2, y2] = point(to, R);
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
};

const FILL = "#4c9aff"; // phần đã đạt: xanh dương
const TRACK = "#e5e7eb"; // phần còn lại: xám nhạt

/** Đồng hồ tốc độ đơn giản: cung xanh đến giá trị, phần còn lại xám nhạt, kim đen, chỉ có nhãn XN bên dưới (không số, không diễn giải). */
export default function SpeedGauge({ label, pct }: Props) {
  const { mode } = useTheme(); // nền tối: kim và chữ phải sáng để tương phản
  const dark = mode === "dark";
  const ink = dark ? "#f1f5f9" : "#111827"; // kim đen (sáng trên nền tối để tương phản)
  const value = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div className="flex w-full flex-col items-center" data-testid={`speed-${label}`}>
      <svg viewBox="0 0 120 66" className="w-full max-w-[220px]" role="img" aria-label={`${label}: ${pct === null ? "chưa có số liệu" : `${value.toFixed(1)}%`}`}>
        <path d={arc(0, 100)} fill="none" stroke={dark ? "#334155" : TRACK} strokeWidth={W} />
        {value > 0 && <path d={arc(0, value)} fill="none" stroke={FILL} strokeWidth={W} />}
        {/* kim: vẽ hướng về 0% (bên trái) rồi xoay theo giá trị */}
        <g style={{ transform: `rotate(${(value / 100) * 180}deg)`, transformOrigin: `${CX}px ${CY}px`, transition: "transform .9s ease-out" }}>
          <polygon points={`${CX - R - 2},${CY} ${CX},${CY - 2.6} ${CX},${CY + 2.6}`} fill={ink} />
        </g>
        <circle cx={CX} cy={CY} r="5" fill={ink} />
      </svg>
      <p className={`mt-1 text-sm font-bold uppercase tracking-wide ${dark ? "text-slate-100" : "text-slate-700"}`}>{label}</p>
    </div>
  );
}
