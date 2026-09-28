import { Flag } from "lucide-react";
import MilestoneCard, { type MilestoneCardData } from "./MilestoneCard";

const MONTH_LABEL = (y: number, m: number) => `${String(m).padStart(2, "0")}/${y}`;

/** WF-01: timeline ngang thật — trục thời gian theo tháng, connector từ mốc tháng xuống card, marker kết thúc roadmap.
 * Không phải hàng card cuộn ngang đơn thuần (đúng yêu cầu GPT UI spec). */
export default function RoadmapTimeline({
  milestones, endDate, endLabel, endProgress, year, dimFn, onOpen,
}: {
  milestones: MilestoneCardData[]; endDate: string | null; endLabel: string; endProgress: number | null; year: number;
  dimFn: (cat: string | null) => boolean; onOpen: (id: number) => void;
}) {
  const months = Array.from({ length: 12 }, (_, i) => i + 1);
  const dayOfYearPct = (iso: string) => {
    const d = new Date(iso);
    const start = new Date(d.getFullYear(), 0, 1).getTime();
    const end = new Date(d.getFullYear(), 11, 31).getTime();
    return ((d.getTime() - start) / (end - start)) * 100;
  };
  const items = milestones.filter((m) => new Date(m.target_date).getFullYear() === year);

  return (
    <div className="overflow-x-auto pb-2">
      <div className="relative min-w-[960px] pr-[190px] pt-2">
        {/* trục + mốc tháng */}
        <div className="relative h-10">
          <div className="absolute left-0 right-0 top-1/2 h-[2px] -translate-y-1/2" style={{ background: "var(--rm-border)" }} />
          {months.map((mo) => (
            <div key={mo} className="absolute top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center" style={{ left: `${((mo - 0.5) / 12) * 100}%` }}>
              <span className="h-2.5 w-2.5 rounded-full ring-4" style={{ background: "var(--rm-surface)", boxShadow: "0 0 0 2px var(--rm-border)" }} />
            </div>
          ))}
        </div>
        <div className="relative mb-2 h-4">
          {months.map((mo) => (
            <span key={mo} className="absolute -translate-x-1/2 text-[10px] font-medium" style={{ left: `${((mo - 0.5) / 12) * 100}%`, color: "var(--rm-text-muted)" }}>{MONTH_LABEL(year, mo)}</span>
          ))}
        </div>

        {/* connector + card mỗi milestone */}
        <div className="relative flex gap-4 pt-6" style={{ minHeight: 190 }}>
          {items.map((m) => {
            const pct = dayOfYearPct(m.target_date);
            return (
              <div key={m.id} className="absolute top-0 w-[190px] -translate-x-1/2" style={{ left: `${pct}%` }}>
                <div className="mx-auto h-6 w-px border-l border-dashed" style={{ borderColor: "var(--rm-border)" }} />
                <MilestoneCard m={m} onClick={() => onOpen(m.id)} dim={dimFn(m.category_name)} />
              </div>
            );
          })}
          {endDate && (
            <div className="absolute top-0 w-[200px] -translate-x-1/2" style={{ left: "100%" }}>
              <div className="mx-auto h-6 w-px border-l border-dashed" style={{ borderColor: "var(--rm-status-ontrack)" }} />
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
