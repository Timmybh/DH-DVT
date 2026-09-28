import { useCallback, useEffect, useState } from "react";
import { Map, Moon, Pencil, Plus, Settings, Sun } from "lucide-react";
import { api, errorMessage } from "../../../api/client";
import { useTheme } from "../../../theme/ThemeContext";
import { AddMilestoneModal, DetailModal, type Category, type MilestoneCard as MilestoneCardT, type Msg } from "../CeoRoadmap";
import CategoryFilter from "./CategoryFilter";
import DisplayOptions from "./DisplayOptions";
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
  const [windowTime, setWindowTime] = useState<WindowTime>("ALL");
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
  useEffect(() => setPage(0), [layout, windowTime, pageMode, versionId]);

  const toggleCat = (c: string) => setDimmed((prev) => { const n = new Set(prev); if (n.has(c)) n.delete(c); else n.add(c); return n; });
  const isDim = (cat: string | null) => !!cat && dimmed.has(cat);

  const thisYear = new Date().getFullYear();
  const filtered = view ? view.milestones.filter((m) => windowTime === "ALL" || new Date(m.target_date).getFullYear() === thisYear) : [];
  const paginating = pageMode === "PAGED" && layout !== "VERTICAL";
  const pageSize = layout === "THREED" ? THREED_PAGE_SIZE : HORIZONTAL_PAGE_SIZE;
  const pageCount = paginating ? Math.max(1, Math.ceil(filtered.length / pageSize)) : 1;
  const curPage = Math.min(page, pageCount - 1);
  const shown = paginating ? filtered.slice(curPage * pageSize, curPage * pageSize + pageSize) : filtered;

  const overall = view && view.summary.length > 0 ? Math.round(view.summary.reduce((s, x) => s + (x.avg_progress_percent ?? 0), 0) / view.summary.length) : null;
  const lastMilestone = filtered.length > 0 ? [...filtered].sort((a, b) => a.target_date.localeCompare(b.target_date))[filtered.length - 1] : null;
  const endDate = lastMilestone ? lastMilestone.target_date : null;
  const endLabel = "Mục tiêu tổng";

  return (
    <div className="roadmap-shell -mx-4 -mt-4 min-h-screen px-4 py-5 sm:-mx-6 sm:px-6" data-testid="rm-page">
      <div className="mx-auto max-w-[1520px] space-y-5">
        {/* header */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--rm-radius-lg)] border p-4" style={{ background: "var(--rm-surface)", borderColor: "var(--rm-border)", boxShadow: "var(--rm-shadow)" }}>
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-2xl" style={{ background: "linear-gradient(135deg,#2563eb,#7c3aed)" }}><Map className="text-white" size={22} /></span>
            <div>
              <h1 className="text-lg font-extrabold leading-tight" style={{ color: "var(--rm-text)" }}>Strategic Roadmap</h1>
              <p className="text-xs" style={{ color: "var(--rm-text-muted)" }}>Quản lý và theo dõi các mục tiêu chiến lược của doanh nghiệp</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select className="rounded-xl border px-3 py-2 text-xs font-medium" style={{ borderColor: "var(--rm-border)", background: "var(--rm-surface)", color: "var(--rm-text)" }} value={versionId ?? ""} onChange={(e) => setVersionId(Number(e.target.value) || null)}>
              <option value="">— Chọn version —</option>
              {scenarios.flatMap((s) => (s.versions ?? []).map((v) => <option key={v.id} value={v.id}>{s.name} · v{v.version_no} ({v.status})</option>))}
            </select>
            <button onClick={toggle} className="flex h-9 w-9 items-center justify-center rounded-xl border" style={{ borderColor: "var(--rm-border)", color: "var(--rm-text)" }} aria-label="Đổi chế độ sáng/tối">{mode === "dark" ? <Sun size={16} /> : <Moon size={16} />}</button>
            {perm.manage && (
              <button onClick={() => setEditMode((v) => !v)} className="flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold text-white" style={{ background: editMode ? "var(--rm-status-ontrack)" : "var(--rm-text)" }} data-testid="rm-edit-toggle">
                <Pencil size={14} />{editMode ? "Đang Edit mode — Xong" : "Edit mode"}
              </button>
            )}
          </div>
        </div>

        {msg && <p className="rounded-xl border px-3 py-2 text-sm" style={{ borderColor: msg.ok ? "var(--rm-status-ontrack)" : "var(--rm-status-behind)", color: msg.ok ? "var(--rm-status-ontrack)" : "var(--rm-status-behind)" }} role="status">{msg.text}</p>}

        {/* filter + legend */}
        <CategoryFilter active={dimmed} onToggle={toggleCat} />

        {!view ? (
          <p className="rounded-[var(--rm-radius-lg)] border border-dashed p-10 text-center text-sm" style={{ borderColor: "var(--rm-border)", color: "var(--rm-text-muted)" }}>Chưa có version nào — tạo Scenario/Version ở "Mô phỏng kỹ thuật" trước.</p>
        ) : (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_340px]">
            {/* 1 khu vực view duy nhất — đổi nội dung theo layout đang chọn, không hiện song song 2 kiểu view */}
            <div className="rounded-[var(--rm-radius-lg)] border p-4" style={{ background: "var(--rm-surface)", borderColor: "var(--rm-border)", boxShadow: "var(--rm-shadow)" }}>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full" style={{ background: "var(--rm-cat-dx-bg)", color: "var(--rm-cat-dx)" }}><Map size={15} /></span>
                  <div>
                    <div className="text-sm font-bold" style={{ color: "var(--rm-text)" }}>Lộ trình mục tiêu chiến lược {thisYear}</div>
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

              {layout === "HORIZONTAL" && <RoadmapTimeline milestones={shown} endDate={endDate} endLabel={endLabel} endProgress={overall} year={thisYear} dimFn={isDim} onOpen={setDetailId} />}
              {layout === "THREED" && <Roadmap3DView milestones={shown} onOpen={setDetailId} endLabel={endLabel} />}
              {layout === "VERTICAL" && <RoadmapListView milestones={filtered} onOpen={setDetailId} endLabel={endLabel} endDate={endDate} endProgress={overall} />}

              {paginating && pageCount > 1 && (
                <div className="mt-3 flex items-center justify-center gap-3 text-xs" style={{ color: "var(--rm-text-muted)" }}>
                  <button className="rounded-lg border px-2 py-1" style={{ borderColor: "var(--rm-border)" }} disabled={curPage === 0} onClick={() => setPage(curPage - 1)}>‹</button>
                  <span>Trang {curPage + 1} / {pageCount}</span>
                  <button className="rounded-lg border px-2 py-1" style={{ borderColor: "var(--rm-border)" }} disabled={curPage >= pageCount - 1} onClick={() => setPage(curPage + 1)}>›</button>
                </div>
              )}
            </div>

            <div className="space-y-5">
              <DisplayOptions windowTime={windowTime} setWindowTime={setWindowTime} pageMode={pageMode} setPageMode={setPageMode} thisYear={thisYear} />
              <a href="/planning/roadmap/setup" className="flex items-center justify-between rounded-[var(--rm-radius-lg)] border p-4 text-sm font-bold" style={{ background: "var(--rm-surface)", borderColor: "var(--rm-border)", color: "var(--rm-text)" }} data-testid="rm-goto-setup">
                <span className="flex items-center gap-2"><Settings size={16} />Thiết lập &amp; dữ liệu</span><span style={{ color: "var(--rm-cat-dx)" }}>Mở →</span>
              </a>
            </div>
          </div>
        )}
      </div>

      {addOpen && versionId !== null && <AddMilestoneModal versionId={versionId} categories={categories} onClose={() => setAddOpen(false)} onDone={() => { setAddOpen(false); void loadView(); }} setMsg={setMsg} />}
      {detailId !== null && <DetailModal milestoneId={detailId} milestones={view?.milestones ?? []} editMode={editMode} categories={categories} onClose={() => setDetailId(null)} onChanged={() => void loadView()} setMsg={setMsg} />}
    </div>
  );
}
