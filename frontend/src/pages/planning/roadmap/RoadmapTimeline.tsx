import { Flag } from "lucide-react";
import { categoryVars } from "./tokens";
import MilestoneCard, { type MilestoneCardData } from "./MilestoneCard";

const MONTH_LABEL = (y: number, m: number) => `${String(m).padStart(2, "0")}/${y}`;
/** Bảng màu xoay vòng cho trục thời gian — line/dot sinh động hơn (thuần trình bày, không gắn business rule). */
const DOT_PALETTE = ["#2563eb", "#7c3aed", "#ea580c", "#16a34a", "#db2777", "#0ea5e9", "#dc2626"];

export default function RoadmapTimeline({
  milestones, endDate, endLabel, endProgress, rangeStart, rangeEnd, dimFn, onOpen,
}: {
  milestones: MilestoneCardData[]; endDate: string | null; endLabel: string; endProgress: number | null;
  rangeStart: Date; rangeEnd: Date; dimFn: (cat: string | null) => boolean; onOpen: (id: number) => void;
}) {
  const months: { y: number; m: number }[] = [];
  { let y = rangeStart.getFullYear(), m = rangeStart.getMonth() + 1;
    while (y < rangeEnd.getFullYear() || (y === rangeEnd.getFullYear() && m <= rangeEnd.getMonth() + 1)) {
      months.push({ y, m });
      m++; if (m > 12) { m = 1; y++; }
    }
  }
  const totalMs = rangeEnd.getTime() - rangeStart.getTime() || 1;
  const pctOf = (iso: string) => Math.max(0, Math.min(100, ((new Date(iso).getTime() - rangeStart.getTime()) / totalMs) * 100));

  return (
    <div className="overflow-x-auto pb-2">
      <div className="relative pr-[190px] pt-2" style={{ minWidth: Math.max(960, months.length * 80) }}>
        {/* trục gradient nhiều màu + mốc tháng */}
        <div className="relative h-10">
          <div className="absolute left-0 right-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full" style={{ background: `linear-gradient(90deg, ${DOT_PALETTE.join(",")})` }} />
          {months.map((mo, i) => (
            <div key={`${mo.y}-${mo.m}`} className="absolute top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center" style={{ left: `${(i / Math.max(1, months.length - 1)) * 100}%` }}>
              <span className="block h-3.5 w-3.5 rounded-full border-[3px] bg-white shadow" style={{ borderColor: DOT_PALETTE[i % DOT_PALETTE.length] }} />
            </div>
          ))}
        </div>
        <div className="relative mb-2 h-4">
          {months.map((mo, i) => (
            <span key={`${mo.y}-${mo.m}`} className="absolute -translate-x-1/2 text-[10px] font-medium" style={{ left: `${(i / Math.max(1, months.length - 1)) * 100}%`, color: "var(--rm-text-muted)" }}>{MONTH_LABEL(mo.y, mo.m)}</span>
          ))}
        </div>

        {/* connector + card mỗi milestone */}
        <div className="relative flex gap-4 pt-6" style={{ minHeight: 190 }}>
          {milestones.map((m) => {
            const pct = pctOf(m.target_date);
            const cv = categoryVars(m.category_name);
            return (
              <div key={m.id} className="absolute top-0 w-[190px] -translate-x-1/2" style={{ left: `${pct}%` }}>
                <div className="mx-auto h-6 w-0.5 rounded-full" style={{ background: cv.fg, opacity: 0.55 }} />
                <MilestoneCard m={m} onClick={() => onOpen(m.id)} dim={dimFn(m.category_name)} />
              </div>
            );
          })}
          {endDate && (
            <div className="absolute top-0 w-[200px] -translate-x-1/2" style={{ left: "100%" }}>
              <div className="mx-auto h-6 w-0.5 rounded-full" style={{ background: "var(--rm-status-ontrack)" }} />
              <div className="rounded-[var(--rm-radius-md)] p-3.5 text-white shadow-lg" style={{ background: "linear-gradient(135deg, var(--rm-status-ontrack), #0d9488)" }}>
                <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-white/85"><Flag size={14} />Kết thúc roadmap</div>
                <div className="mt-1 text-sm font-bold">{MONTH_LABEL(new Date(endDate).getFullYear(), new Date(endDate).getMonth() + 1)}</div>
                <div className="text-[11px] text-white/80">{endLabel}</div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/25"><div className="h-full rounded-full bg-white" style={{ width: `${endProgress ?? 0}%` }} /></div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
