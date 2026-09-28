import { useCallback, useEffect, useState } from "react";
import { CalendarDays, Layers, Map, Moon, Pencil, Plus, Settings, Sun } from "lucide-react";
import { api, errorMessage } from "../../../api/client";
import { useTheme } from "../../../theme/ThemeContext";
import { AddMilestoneModal, DetailModal, type Category, type MilestoneCard as MilestoneCardT, type Msg } from "../CeoRoadmap";
import CategoryFilter from "./CategoryFilter";
import Roadmap3DView from "./Roadmap3DView";
import RoadmapListView from "./RoadmapListView";
import RoadmapTimeline from "./RoadmapTimeline";
import type { Layout, PageMode, WindowTime } from "./types";

const RES = "/roadmap";
const HORIZONTAL_PAGE_SIZE = 5;
const THREED_PAGE_SIZE = 4;

interface ScenarioRow { id: number; scenario_code: string; name: string; status: string; versions?: { id: number; version_no: number; status: string; note: string }[] }
interface CeoView { version_id: number; milestones: MilestoneCardT[]; summary: { category_code: string; category_name: string; category_color: string; avg_progress_percent: number | null }[] }

/** WF-01/01B/01C theo bộ ảnh GPT UI duyệt 2026-09-28 — trang chủ Strategic Roadmap: header, legend, timeline
 * ngang cố định + panel view lớn (Ngang/3D/Dọc chuyển đổi) + list view phụ + Tùy chọn hiển thị. */
export default function CeoRoadmapPage({ perm }: { perm: { manage: boolean } }) {
  const { mode, toggle } = useTheme();
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([]);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [view, setView] = useState<CeoView | null>(null);
  const [dimmed, setDimmed] = useState<Set<string>>(new Set());
  const [editMode, setEditMode] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [layout, setLayout] = useState<Layout>("THREED");
  const [windowTime, setWindowTime] = useState<WindowTime>("YEAR");
  const thisYearNow = new Date().getFullYear();
  const [customFrom, setCustomFrom] = useState(thisYearNow);
  const [customTo, setCustomTo] = useState(thisYearNow);
  const [pageMode, setPageMode] = useState<PageMode>("FULL");
  const [page, setPage] = useState(0);
  const [msg, setMsg] = useState<Msg>(null);

  const loadScenarios = useCallback(async () => {
    const list = (await api.get<ScenarioRow[]>(`${RES}/scenarios`)).data;
    const withVersions = await Promise.all(list.map(async (s) => (await api.get<ScenarioRow>(`${RES}/scenarios/${s.id}`)).data));
    setScenarios(withVersions);
    setVersionId((cur) => cur ?? withVersions.flatMap((s) => s.versions ?? [])[0]?.id ?? null);
  }, []);
  const loadView = useCallback(async () => {
    if (versionId === null) return;
    try { setView((await api.get<CeoView>(`${RES}/versions/${versionId}/ceo-view`)).data); }
    catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  }, [versionId]);
  useEffect(() => { api.get<Category[]>(`${RES}/categories`).then((r) => setCategories(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) })); void loadScenarios(); }, [loadScenarios]);
  useEffect(() => { void loadView(); }, [loadView]);
  useEffect(() => setPage(0), [layout, windowTime, pageMode, versionId, customFrom, customTo]);

  const toggleCat = (c: string) => setDimmed((prev) => { const n = new Set(prev); if (n.has(c)) n.delete(c); else n.add(c); return n; });
  const isDim = (cat: string | null) => !!cat && dimmed.has(cat);

  const thisYear = thisYearNow;
  const fromYear = windowTime === "YEAR" ? thisYear : windowTime === "NEXT_YEAR" ? thisYear + 1 : Math.min(customFrom, customTo);
  const toYear = windowTime === "YEAR" ? thisYear : windowTime === "NEXT_YEAR" ? thisYear + 1 : Math.max(customFrom, customTo);
  const rangeStart = new Date(fromYear, 0, 1);
  const rangeEnd = new Date(toYear, 11, 31);
  const filtered = view ? view.milestones.filter((m) => { const y = new Date(m.target_date).getFullYear(); return y >= fromYear && y <= toYear; }) : [];
  const paginating = pageMode === "PAGED" && layout !== "VERTICAL";
  const pageSize = layout === "THREED" ? THREED_PAGE_SIZE : HORIZONTAL_PAGE_SIZE;
  const pageCount = paginating ? Math.max(1, Math.ceil(filtered.length / pageSize)) : 1;
  const curPage = Math.min(page, pageCount - 1);
  const shown = paginating ? filtered.slice(curPage * pageSize, curPage * pageSize + pageSize) : filtered;

  const overall = view && view.summary.length > 0 ? Math.round(view.summary.reduce((s, x) => s + (x.avg_progress_percent ?? 0), 0) / view.summary.length) : null;
  // Card "Kết thúc roadmap" luôn neo đúng NGÀY CUỐI của Window Time đang xem (không phải milestone cuối) — Toàn trình/Phân trang thay đổi Window Time thì mốc này đổi theo.
  const endDate = view ? `${toYear}-${String(rangeEnd.getMonth() + 1).padStart(2, "0")}-${String(rangeEnd.getDate()).padStart(2, "0")}` : null;
  const endLabel = "Mục tiêu tổng";

  return (
    <div className="roadmap-shell flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-5 sm:px-6" data-testid="rm-page">
      <div className="flex w-full flex-1 flex-col gap-5">
        {/* header */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--rm-radius-lg)] border p-4" style={{ background: "var(--rm-surface)", borderColor: "var(--rm-border)", boxShadow: "var(--rm-shadow)" }}>
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl" style={{ background: "linear-gradient(135deg,#2563eb,#7c3aed)" }}><Map className="text-white" size={22} /></span>
            <div className="min-w-0">
              <h1 className="text-lg font-extrabold leading-tight" style={{ color: "var(--rm-text)" }}>Strategic Roadmap</h1>
              <p className="truncate text-xs sm:whitespace-normal" style={{ color: "var(--rm-text-muted)" }}>Quản lý và theo dõi các mục tiêu chiến lược của doanh nghiệp</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select className="rounded-xl border px-3 py-2 text-xs font-medium" style={{ borderColor: "var(--rm-border)", background: "var(--rm-surface)", color: "var(--rm-text)" }} value={versionId ?? ""} onChange={(e) => setVersionId(Number(e.target.value) || null)}>
              <option value="">— Chọn version —</option>
              {scenarios.flatMap((s) => (s.versions ?? []).map((v) => <option key={v.id} value={v.id}>{s.name} · v{v.version_no} ({v.status})</option>))}
            </select>

            <div className="flex items-center gap-1 rounded-xl border px-2" style={{ borderColor: "var(--rm-border)" }}>
              <CalendarDays size={13} style={{ color: "var(--rm-text-muted)" }} />
              <select value={windowTime} onChange={(e) => setWindowTime(e.target.value as WindowTime)} className="border-0 bg-transparent py-2 text-xs font-semibold outline-none" style={{ color: "var(--rm-text)" }} data-testid="rm-window-select" aria-label="Khoảng thời gian">
                <option value="YEAR">Năm nay</option>
                <option value="NEXT_YEAR">Năm tới</option>
                <option value="CUSTOM">Tùy chỉnh năm</option>
              </select>
            </div>
            {windowTime === "CUSTOM" && (
              <div className="flex items-center gap-1 rounded-xl border px-2 py-1" style={{ borderColor: "var(--rm-border)" }} data-testid="rm-custom-year-range">
                <input type="number" value={customFrom} onChange={(e) => setCustomFrom(Number(e.target.value) || thisYear)} className="w-16 rounded-lg border px-1.5 py-1 text-[11px]" style={{ borderColor: "var(--rm-border)", color: "var(--rm-text)" }} aria-label="Từ năm" />
                <span className="text-[11px]" style={{ color: "var(--rm-text-muted)" }}>đến</span>
                <input type="number" value={customTo} onChange={(e) => setCustomTo(Number(e.target.value) || thisYear)} className="w-16 rounded-lg border px-1.5 py-1 text-[11px]" style={{ borderColor: "var(--rm-border)", color: "var(--rm-text)" }} aria-label="Đến năm" />
              </div>
            )}
            <div className="flex items-center gap-1 rounded-xl border px-2" style={{ borderColor: "var(--rm-border)" }}>
              <Layers size={13} style={{ color: "var(--rm-text-muted)" }} />
              <select value={pageMode} onChange={(e) => setPageMode(e.target.value as PageMode)} className="border-0 bg-transparent py-2 text-xs font-semibold outline-none" style={{ color: "var(--rm-text)" }} data-testid="rm-page-select" aria-label="Loại trình bày trang">
                <option value="FULL">Toàn trình</option>
                <option value="PAGED">Phân trang</option>
              </select>
            </div>

            <button onClick={toggle} className="flex h-9 w-9 items-center justify-center rounded-xl border" style={{ borderColor: "var(--rm-border)", color: "var(--rm-text)" }} aria-label="Đổi chế độ sáng/tối">{mode === "dark" ? <Sun size={16} /> : <Moon size={16} />}</button>
            {perm.manage && (
              <button onClick={() => setEditMode((v) => !v)} className="flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold text-white" style={{ background: editMode ? "var(--rm-status-ontrack)" : "var(--rm-text)" }} data-testid="rm-edit-toggle">
                <Pencil size={14} />{editMode ? "Đang Edit mode — Xong" : "Edit mode"}
              </button>
            )}
            <a href="/planning/roadmap/setup" className="flex h-9 w-9 items-center justify-center rounded-xl border" style={{ borderColor: "var(--rm-border)", color: "var(--rm-text)" }} aria-label="Thiết lập & dữ liệu" title="Thiết lập & dữ liệu" data-testid="rm-goto-setup"><Settings size={16} /></a>
          </div>
        </div>

        {msg && <p className="rounded-xl border px-3 py-2 text-sm" style={{ borderColor: msg.ok ? "var(--rm-status-ontrack)" : "var(--rm-status-behind)", color: msg.ok ? "var(--rm-status-ontrack)" : "var(--rm-status-behind)" }} role="status">{msg.text}</p>}

        {/* filter + legend */}
        <CategoryFilter active={dimmed} onToggle={toggleCat} />

        {!view ? (
          <p className="rounded-[var(--rm-radius-lg)] border border-dashed p-10 text-center text-sm" style={{ borderColor: "var(--rm-border)", color: "var(--rm-text-muted)" }}>Chưa có version nào — tạo Scenario/Version ở "Mô phỏng kỹ thuật" trước.</p>
        ) : (
          <>
            {/* 1 khu vực view duy nhất — đổi nội dung theo layout đang chọn, cao hết phần còn lại của màn hình */}
            <div className="flex flex-1 flex-col rounded-[var(--rm-radius-lg)] border p-4" style={{ background: "var(--rm-surface)", borderColor: "var(--rm-border)", boxShadow: "var(--rm-shadow)" }}>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full" style={{ background: "var(--rm-cat-dx-bg)", color: "var(--rm-cat-dx)" }}><Map size={15} /></span>
                  <div>
                    <div className="text-sm font-bold" style={{ color: "var(--rm-text)" }}>Lộ trình mục tiêu chiến lược {fromYear === toYear ? fromYear : `${fromYear}–${toYear}`}</div>
                    <div className="text-[11px]" style={{ color: "var(--rm-text-muted)" }}>Các cột mốc quan trọng theo thời gian</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {editMode && perm.manage && (
                    <button onClick={() => setAddOpen(true)} className="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold text-white" style={{ background: "var(--rm-cat-dx)" }} data-testid="rm-add-milestone"><Plus size={14} />Milestone</button>
                  )}
                  <div className="flex gap-1 rounded-xl p-1" style={{ background: "var(--rm-surface-tint)" }}>
                    {([["HORIZONTAL", "View ngang"], ["THREED", "View 3D"], ["VERTICAL", "View dọc"]] as [Layout, string][]).map(([v, label]) => (
                      <button key={v} onClick={() => setLayout(v)} className="rounded-lg px-3 py-1.5 text-xs font-semibold" style={layout === v ? { background: "var(--rm-cat-dx)", color: "#fff" } : { color: "var(--rm-text-muted)" }} data-testid={`rm-big-layout-${v}`}>{label}</button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex flex-1 flex-col">
                {layout === "HORIZONTAL" && <RoadmapTimeline milestones={shown} endDate={endDate} endLabel={endLabel} endProgress={overall} rangeStart={rangeStart} rangeEnd={rangeEnd} dimFn={isDim} onOpen={setDetailId} />}
                {layout === "THREED" && <Roadmap3DView milestones={shown} onOpen={setDetailId} endLabel={endLabel} endDate={endDate} />}
                {layout === "VERTICAL" && <RoadmapListView milestones={filtered} onOpen={setDetailId} endLabel={endLabel} endDate={endDate} endProgress={overall} />}
              </div>

              {paginating && pageCount > 1 && (
                <div className="mt-3 flex items-center justify-center gap-3 text-xs" style={{ color: "var(--rm-text-muted)" }}>
                  <button className="rounded-lg border px-2 py-1" style={{ borderColor: "var(--rm-border)" }} disabled={curPage === 0} onClick={() => setPage(curPage - 1)}>‹</button>
                  <span>Trang {curPage + 1} / {pageCount}</span>
                  <button className="rounded-lg border px-2 py-1" style={{ borderColor: "var(--rm-border)" }} disabled={curPage >= pageCount - 1} onClick={() => setPage(curPage + 1)}>›</button>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {addOpen && versionId !== null && <AddMilestoneModal versionId={versionId} categories={categories} onClose={() => setAddOpen(false)} onDone={() => { setAddOpen(false); void loadView(); }} setMsg={setMsg} />}
      {detailId !== null && <DetailModal milestoneId={detailId} milestones={view?.milestones ?? []} editMode={editMode} categories={categories} onClose={() => setDetailId(null)} onChanged={() => void loadView()} setMsg={setMsg} />}
    </div>
  );
}
