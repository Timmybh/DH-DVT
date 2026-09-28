import { Flag } from "lucide-react";
import { categoryIcon, categoryVars } from "./tokens";
import StatusBadge from "./StatusBadge";
import type { MilestoneCardData } from "./MilestoneCard";

const dateVi = (iso: string) => { const d = new Date(iso); return `${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`; };

/** WF-01C View dọc — cũng dùng làm panel "View đọc (danh sách theo thời gian)" cạnh View 3D/Ngang. */
export default function RoadmapListView({ milestones, onOpen, endLabel, endDate, endProgress }: {
  milestones: MilestoneCardData[]; onOpen: (id: number) => void; endLabel: string; endDate: string | null; endProgress: number | null;
}) {
  return (
    <div className="space-y-1.5">
      {milestones.map((m) => {
        const cv = categoryVars(m.category_name);
        const Icon = categoryIcon(m.category_name);
        return (
          <button key={m.id} onClick={() => onOpen(m.id)} className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left transition hover:bg-[var(--rm-surface-tint)]" data-testid={`rm-list-ms-${m.id}`}>
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full" style={{ background: cv.bg, color: cv.fg }}><Icon size={13} /></span>
            <span className="w-14 shrink-0 text-[11px]" style={{ color: "var(--rm-text-muted)" }}>{dateVi(m.target_date)}</span>
            <span className="flex-1 truncate text-xs font-semibold" style={{ color: "var(--rm-text)" }}>{m.name || m.code}</span>
            <span className="h-1.5 w-16 shrink-0 overflow-hidden rounded-full" style={{ background: "var(--rm-border)" }}><span className="block h-full rounded-full" style={{ width: `${m.progress_percent ?? 0}%`, background: cv.fg }} /></span>
            <span className="w-10 shrink-0 text-right text-[11px] font-bold" style={{ color: cv.fg }}>{m.progress_percent ?? 0}%</span>
          </button>
        );
      })}
      {endDate && (
        <div className="flex items-center gap-2.5 rounded-xl px-2 py-2" style={{ background: "var(--rm-status-ontrack-bg)" }}>
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-white" style={{ background: "var(--rm-status-ontrack)" }}><Flag size={13} /></span>
          <span className="w-14 shrink-0 text-[11px]" style={{ color: "var(--rm-text-muted)" }}>{dateVi(endDate)}</span>
          <span className="flex-1 truncate text-xs font-bold" style={{ color: "var(--rm-status-ontrack)" }}>{endLabel}</span>
          <span className="w-10 shrink-0 text-right text-[11px] font-bold" style={{ color: "var(--rm-status-ontrack)" }}>{endProgress ?? 0}%</span>
        </div>
      )}
      {milestones.length === 0 && <p className="py-6 text-center text-xs" style={{ color: "var(--rm-text-muted)" }}>Không có milestone trong khoảng thời gian này.</p>}
    </div>
  );
}
