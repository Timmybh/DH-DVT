import { Flag } from "lucide-react";
import { categoryVars } from "./tokens";
import type { MilestoneCardData } from "./MilestoneCard";

const dateVi = (iso: string) => { const d = new Date(iso); return `${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`; };

/** WF-01B — "cảm giác con đường chiến lược": minh hoạ SVG núi/đường (không raster hoá UI), milestone là
 * component HTML thật đặt theo % dọc đường (path tĩnh), không phải CSS 3D transform như bản kỹ thuật trước. */
export default function Roadmap3DView({ milestones, onOpen, endLabel }: { milestones: MilestoneCardData[]; onOpen: (id: number) => void; endLabel: string }) {
  const items = milestones.slice(0, 6);
  const n = items.length + 1; // +1 cho điểm kết thúc
  // toạ độ % dọc theo "đường" từ góc dưới-trái lên góc trên-phải, so le trái/phải quanh path
  const pointAt = (i: number, total: number) => {
    const t = total <= 1 ? 1 : i / (total - 1);
    const x = 8 + t * 82;
    const y = 82 - t * 62 + (i % 2 === 0 ? 6 : -6);
    return { x, y };
  };

  return (
    <div className="relative overflow-hidden rounded-[var(--rm-radius-lg)] border" style={{ borderColor: "var(--rm-border)", height: 460, background: "linear-gradient(180deg,#bfe3ff 0%,#e8f4ff 38%,#eef7ee 60%,#e6f2e1 100%)" }}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
        <polygon points="0,55 15,30 28,48 40,22 55,46 68,28 80,44 100,34 100,60 0,60" fill="#9fb8cf" opacity="0.55" />
        <polygon points="0,62 20,42 35,58 50,38 66,58 82,40 100,52 100,68 0,68" fill="#7f9db8" opacity="0.6" />
        <path d="M -5 100 C 20 78, 30 68, 45 58 C 62 47, 70 40, 105 18" stroke="#e7ebf1" strokeWidth="11" fill="none" />
        <path d="M -5 100 C 20 78, 30 68, 45 58 C 62 47, 70 40, 105 18" stroke="#cbd3de" strokeWidth="11.6" fill="none" opacity="0.5" style={{ mixBlendMode: "multiply" }} />
        <path d="M -5 100 C 20 78, 30 68, 45 58 C 62 47, 70 40, 105 18" stroke="#fff" strokeWidth="0.8" strokeDasharray="2.4 2.2" fill="none" opacity="0.9" />
      </svg>

      {items.map((m, i) => {
        const { x, y } = pointAt(i, n);
        const cv = categoryVars(m.category_name);
        return (
          <button
            key={m.id} onClick={() => onOpen(m.id)} data-testid={`rm-3d-ms-${m.id}`}
            aria-label={`${m.category_name || "Chưa phân loại"}, ${m.name || m.code}, ${dateVi(m.target_date)}, ${m.progress_percent ?? 0} phần trăm`}
            className="absolute w-[168px] -translate-x-1/2 -translate-y-full rounded-[var(--rm-radius-md)] border p-3 text-left shadow-lg transition hover:-translate-y-[105%]"
            style={{ left: `${x}%`, top: `${y}%`, background: "var(--rm-surface)", borderColor: "var(--rm-border)" }}
          >
            <span className="mb-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold" style={{ color: cv.fg, background: cv.bg }}>{m.category_name || "Chưa phân loại"}</span>
            <div className="flex items-baseline justify-between"><div className="text-xs font-bold leading-tight">{m.name || m.code}</div><div className="text-sm font-extrabold" style={{ color: cv.fg }}>{m.progress_percent ?? 0}%</div></div>
            <div className="mt-1 text-[10px]" style={{ color: "var(--rm-text-muted)" }}>{dateVi(m.target_date)}</div>
            <span className="absolute -bottom-2 left-1/2 h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-white" style={{ background: cv.fg }} />
          </button>
        );
      })}

      {(() => { const { x, y } = pointAt(items.length, n); return (
        <div className="absolute w-[180px] -translate-x-1/2 -translate-y-full rounded-[var(--rm-radius-md)] p-3 text-white shadow-xl" style={{ left: `${x}%`, top: `${y}%`, background: "linear-gradient(135deg, var(--rm-status-ontrack), #0d9488)" }}>
          <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-white/85"><Flag size={13} />Kết thúc roadmap</div>
          <div className="mt-1 text-xs font-bold">{endLabel}</div>
          <span className="absolute -bottom-2 left-1/2 h-4 w-4 -translate-x-1/2 rounded-full border-2 border-white" style={{ background: "var(--rm-status-ontrack)" }} />
        </div>
      ); })()}
      <p className="absolute bottom-2 right-3 text-[10px]" style={{ color: "var(--rm-text-muted)" }}>View 3D là chế độ trình bày — Edit Mode dùng ở View ngang.</p>
    </div>
  );
}
