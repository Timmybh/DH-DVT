import { Flag } from "lucide-react";
import { categoryVars } from "./tokens";
import MilestoneCard, { type MilestoneCardData } from "./MilestoneCard";

const MONTH_LABEL = (y: number, m: number) => `${String(m).padStart(2, "0")}/${y}`;
/** Bảng màu xoay vòng cho trục thời gian — line/dot sinh động hơn (thuần trình bày, không gắn business rule). */
const DOT_PALETTE = ["#2563eb", "#7c3aed", "#ea580c", "#16a34a", "#db2777", "#0ea5e9", "#dc2626"];
const CARD_W = 190;
const END_W = 200;
const GAP = 22;
const CONNECTOR_H = 34; // khoảng cách từ trục xuống mép trên card — chỗ cho đường gãy khúc đi ngang

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
  const pctOf = (d: Date) => Math.max(0, Math.min(1, (d.getTime() - rangeStart.getTime()) / totalMs));
  const TOTAL_W = Math.max(1100, months.length * 130 + END_W + 80);
  const xOf = (iso: string) => pctOf(new Date(iso)) * (TOTAL_W - END_W - 40);

  // Sắp card theo thời gian thật, tự né chồng lấn (chỉ đẩy sang phải), điểm neo mốc thời gian giữ nguyên vị trí thật
  const sorted = [...milestones].sort((a, b) => a.target_date.localeCompare(b.target_date));
  let prevRight = -Infinity;
  const placed = sorted.map((m) => {
    const idealCx = xOf(m.target_date);
    const idealLeft = idealCx - CARD_W / 2;
    const actualLeft = Math.max(idealLeft, prevRight + GAP);
    prevRight = actualLeft + CARD_W;
    return { m, idealCx, actualLeft, actualCx: actualLeft + CARD_W / 2 };
  });
  const endIdealCx = endDate ? xOf(endDate) : TOTAL_W - END_W / 2;
  const endActualLeft = Math.max(endIdealCx - END_W / 2, prevRight + GAP, TOTAL_W - END_W);
  const endActualCx = endActualLeft + END_W / 2;
  const containerW = Math.max(TOTAL_W, endActualLeft + END_W + 20);
  const rowH = 190;
  const midY = CONNECTOR_H * 0.55;

  return (
    <div className="overflow-x-auto pb-2">
      <div className="relative pt-2" style={{ width: containerW }}>
        {/* trục gradient nhiều màu + mốc tháng — mỗi mốc neo đúng vị trí ngày thật (khớp hệ toạ độ với card) */}
        <div className="relative h-10">
          <div className="absolute left-0 right-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full" style={{ background: `linear-gradient(90deg, ${DOT_PALETTE.join(",")})` }} />
          {months.map((mo, i) => (
            <div key={`${mo.y}-${mo.m}`} className="absolute top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center" style={{ left: xOf(`${mo.y}-${String(mo.m).padStart(2, "0")}-01`) }}>
              <span className="block h-3.5 w-3.5 rounded-full border-[3px] bg-white shadow" style={{ borderColor: DOT_PALETTE[i % DOT_PALETTE.length] }} />
            </div>
          ))}
        </div>
        <div className="relative mb-1 h-4">
          {months.map((mo) => (
            <span key={`${mo.y}-${mo.m}`} className="absolute -translate-x-1/2 text-[10px] font-medium" style={{ left: xOf(`${mo.y}-${String(mo.m).padStart(2, "0")}-01`), color: "var(--rm-text-muted)" }}>{MONTH_LABEL(mo.y, mo.m)}</span>
          ))}
        </div>

        {/* connector gãy khúc (elbow): đi thẳng từ mốc thời gian thật xuống, tạt ngang, rồi thẳng vào card */}
        <svg className="absolute left-0" style={{ top: 56, width: containerW, height: CONNECTOR_H, overflow: "visible" }} aria-hidden="true">
          {placed.map(({ m, idealCx, actualCx }) => {
            const cv = categoryVars(m.category_name);
            return <path key={m.id} d={`M ${idealCx} 0 L ${idealCx} ${midY} L ${actualCx} ${midY} L ${actualCx} ${CONNECTOR_H}`} fill="none" stroke={cv.fg} strokeWidth={1.75} strokeOpacity={0.6} strokeLinecap="round" strokeLinejoin="round" />;
          })}
          {endDate && <path d={`M ${endIdealCx} 0 L ${endIdealCx} ${midY} L ${endActualCx} ${midY} L ${endActualCx} ${CONNECTOR_H}`} fill="none" stroke="var(--rm-status-ontrack)" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" />}
        </svg>

        {/* card — đặt đúng vị trí đã né chồng lấn, không tràn khỏi vùng chứa */}
        <div className="relative" style={{ height: rowH, marginTop: CONNECTOR_H }}>
          {placed.map(({ m, actualLeft }) => (
            <div key={m.id} className="absolute top-0" style={{ left: actualLeft, width: CARD_W }}>
              <MilestoneCard m={m} onClick={() => onOpen(m.id)} dim={dimFn(m.category_name)} />
            </div>
          ))}
          {endDate && (
            <div className="absolute top-0" style={{ left: endActualLeft, width: END_W }}>
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
