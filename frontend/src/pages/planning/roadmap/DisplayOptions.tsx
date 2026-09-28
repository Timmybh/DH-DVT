import { Boxes, CalendarDays, Layers, Lightbulb, List, Rows3 } from "lucide-react";
import type { Layout, PageMode, WindowTime } from "./types";

const seg = (active: boolean) => `rounded-lg px-3 py-1.5 text-xs font-semibold transition ${active ? "text-white" : ""}`;
const segStyle = (active: boolean) => (active ? { background: "var(--rm-text)" } : { background: "var(--rm-surface-tint)", color: "var(--rm-text-muted)" });

/** WF-01 "Tùy chọn hiển thị" — gộp Window time / Phân trang / Layout thành 1 khối, đúng bố cục ảnh tham chiếu. */
export default function DisplayOptions({
  windowTime, setWindowTime, pageMode, setPageMode, layout, setLayout, thisYear,
}: {
  windowTime: WindowTime; setWindowTime: (v: WindowTime) => void; pageMode: PageMode; setPageMode: (v: PageMode) => void;
  layout: Layout; setLayout: (v: Layout) => void; thisYear: number;
}) {
  return (
    <div className="rounded-[var(--rm-radius-lg)] border p-4" style={{ background: "linear-gradient(180deg, #fffbeb, var(--rm-surface))", borderColor: "var(--rm-border)" }}>
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-full" style={{ background: "var(--rm-status-risk-bg)", color: "var(--rm-status-risk)" }}><Lightbulb size={16} /></span>
        <div>
          <div className="text-sm font-bold" style={{ color: "var(--rm-text)" }}>Tùy chọn hiển thị</div>
          <div className="text-[11px]" style={{ color: "var(--rm-text-muted)" }}>Các chế độ xem hỗ trợ phân tích và trình bày lộ trình</div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold" style={{ color: "var(--rm-text-muted)" }}><CalendarDays size={13} />Khoảng thời gian (Window time)</div>
          <div className="flex gap-1 rounded-xl p-1" style={{ background: "var(--rm-surface-tint)" }}>
            <button onClick={() => setWindowTime("ALL")} className={seg(windowTime === "ALL")} style={segStyle(windowTime === "ALL")} data-testid="rm-window-all">Toàn trình</button>
            <button onClick={() => setWindowTime("YEAR")} className={seg(windowTime === "YEAR")} style={segStyle(windowTime === "YEAR")} data-testid="rm-window-year">Năm nay</button>
          </div>
        </div>
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold" style={{ color: "var(--rm-text-muted)" }}><Layers size={13} />Phân trang</div>
          <div className="flex gap-1 rounded-xl p-1" style={{ background: "var(--rm-surface-tint)" }}>
            <button onClick={() => setPageMode("FULL")} className={seg(pageMode === "FULL")} style={segStyle(pageMode === "FULL")} data-testid="rm-page-full">Toàn trình</button>
            <button onClick={() => setPageMode("PAGED")} className={seg(pageMode === "PAGED")} style={segStyle(pageMode === "PAGED")} data-testid="rm-page-paged">Phân trang</button>
          </div>
        </div>
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold" style={{ color: "var(--rm-text-muted)" }}><Boxes size={13} />Layout hiển thị</div>
          <div className="flex flex-col gap-1 rounded-xl p-1" style={{ background: "var(--rm-surface-tint)" }}>
            <button onClick={() => setLayout("HORIZONTAL")} className={`flex items-center gap-1.5 ${seg(layout === "HORIZONTAL")}`} style={segStyle(layout === "HORIZONTAL")} data-testid="rm-layout-horizontal"><Rows3 size={13} />View ngang</button>
            <button onClick={() => setLayout("THREED")} className={`flex items-center gap-1.5 ${seg(layout === "THREED")}`} style={segStyle(layout === "THREED")} data-testid="rm-layout-3d"><Boxes size={13} />View 3D</button>
            <button onClick={() => setLayout("VERTICAL")} className={`flex items-center gap-1.5 ${seg(layout === "VERTICAL")}`} style={segStyle(layout === "VERTICAL")} data-testid="rm-layout-vertical"><List size={13} />View dọc</button>
          </div>
        </div>
      </div>
      <p className="mt-3 text-[10px]" style={{ color: "var(--rm-text-muted)" }}>Năm hiển thị: {thisYear} · Phân trang áp dụng cho View ngang &amp; View 3D; View dọc luôn hiện toàn trình.</p>
    </div>
  );
}
