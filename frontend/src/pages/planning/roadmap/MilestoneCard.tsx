import { AlertTriangle, GripVertical } from "lucide-react";
import { categoryIcon, categoryVars } from "./tokens";
import StatusBadge from "./StatusBadge";

export interface MilestoneCardData {
  id: number; code: string; name: string; target_date: string; category_name: string | null;
  progress_percent: number | null; status: "ON_TRACK" | "AT_RISK" | "BEHIND"; has_warning: boolean; warning_note: string;
}

const dateVi = (iso: string) => { const d = new Date(iso); return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`; };
const monthYear = (iso: string) => { const d = new Date(iso); return `${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`; };

/** Card milestone — dùng chung Timeline (Ngang), 3D và List View để đảm bảo cùng 1 style trên mọi layout.
 *  editMode: hiện tay nắm kéo (góc trên-phải) để dời ngày trên trục — kéo xong onDragStart báo RoadmapTimeline tính lại ngày. */
export default function MilestoneCard({ m, onClick, dim, compact, editMode, onDragStart, dragging }: {
  m: MilestoneCardData; onClick: () => void; dim?: boolean; compact?: boolean;
  editMode?: boolean; onDragStart?: (e: React.MouseEvent) => void; dragging?: boolean;
}) {
  const cv = categoryVars(m.category_name);
  const Icon = categoryIcon(m.category_name);
  return (
    <button
      onClick={onClick}
      className="group relative flex h-full w-full flex-col justify-between overflow-hidden rounded-[var(--rm-radius-md)] border text-left transition hover:-translate-y-0.5"
      style={{ background: "var(--rm-surface)", borderColor: "var(--rm-border)", boxShadow: dragging ? "0 8px 24px rgba(0,0,0,.25)" : "var(--rm-shadow)", opacity: dim ? 0.35 : 1, padding: compact ? 10 : 14, cursor: editMode ? "grab" : "pointer" }}
      data-testid={`rm-milestone-${m.id}`}
    >
      {editMode && (
        <span
          role="button"
          aria-label="Kéo để dời ngày"
          title="Kéo để dời ngày"
          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); onDragStart?.(e); }}
          className="absolute right-1.5 top-1.5 flex h-5 w-5 cursor-grab items-center justify-center rounded-md text-white/90 active:cursor-grabbing"
          style={{ background: "rgba(15,23,42,.55)" }}
          data-testid={`rm-milestone-drag-${m.id}`}
        >
          <GripVertical size={12} />
        </span>
      )}
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-2 rounded-full py-1 pl-1 pr-2.5 text-[11px] font-semibold" style={{ color: cv.fg, background: cv.bg }}>
          <span className="flex items-center justify-center rounded-full" style={{ width: compact ? 20 : 24, height: compact ? 20 : 24, background: cv.fg }}><Icon size={compact ? 12 : 14} strokeWidth={2.5} color="#fff" /></span>
          {m.category_name || "Chưa phân loại"}
        </span>
        {m.has_warning && <span title={m.warning_note} className="flex h-6 w-6 items-center justify-center rounded-full" style={{ background: "var(--rm-status-risk-bg)", color: "var(--rm-status-risk)" }}><AlertTriangle size={14} /></span>}
      </div>
      <div className="mt-2 flex items-baseline justify-between gap-2">
        <div className="text-sm font-bold leading-snug" style={{ color: "var(--rm-text)" }}>{m.name || m.code}</div>
        <div className="shrink-0 text-lg font-extrabold" style={{ color: cv.fg }}>{m.progress_percent === null ? "—" : `${Math.round(m.progress_percent)}%`}</div>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full" style={{ background: "var(--rm-border)" }}>
        <div className="h-full rounded-full" style={{ width: `${m.progress_percent ?? 0}%`, background: cv.fg }} />
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[11px]" style={{ color: "var(--rm-text-muted)" }}>{compact ? monthYear(m.target_date) : dateVi(m.target_date)}</span>
        <StatusBadge status={m.status} progressPercent={m.progress_percent} size="sm" />
      </div>
    </button>
  );
}
