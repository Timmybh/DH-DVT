import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { dateVi } from "../../lib/format";

const RES = "/roadmap";
const inp = "w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
const btn = "rounded-full border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40";
const primary = "rounded-full bg-slate-900 px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-40";

type Msg = { ok: boolean; text: string } | null;

interface ScenarioRow { id: number; scenario_code: string; name: string; status: string; versions?: { id: number; version_no: number; status: string; note: string }[] }
interface Category { id: number; code: string; name: string; color: string; sort_order: number; active: boolean }
interface MilestoneCard {
  id: number; code: string; name: string; target_date: string; sequence: number;
  category_code: string | null; category_name: string; category_color: string;
  progress_percent: number | null; status: "ON_TRACK" | "AT_RISK" | "BEHIND";
  baseline_label: string; gap_label: string; proposal_summary: string; has_warning: boolean; warning_note: string;
  measurement_family: "MANUAL_PROGRESS" | "MANUAL_VALUE" | "OPERATIONAL"; measurement_metric_code: string | null;
  measurement_scope_type: string; measurement_scope_value: string; measurement_period_type: string;
  measurement_period_year: number | null; measurement_period_month: number | null; measurement_target_value: number | null;
}
const MEASUREMENT_FAMILY_LABEL: Record<string, string> = { MANUAL_PROGRESS: "Manual Progress (nhập tay %)", MANUAL_VALUE: "Manual Value (nhập tay)", OPERATIONAL: "Operational Data (tự tính từ dữ liệu thật)" };
interface CeoView {
  version_id: number; scenario_id: number; version_no: number; version_status: string;
  milestones: MilestoneCard[];
  summary: { category_code: string; category_name: string; category_color: string; milestone_count: number; avg_progress_percent: number | null }[];
}
interface ActionRow {
  id: number; milestone_id: number; action_type: "ACTION" | "MILESTONE_LINK"; title: string;
  ref_milestone_id: number | null; ref_milestone_code: string; ref_milestone_date: string | null;
  value_type: string; status: "COMPLETED" | "NOT_COMPLETED" | "AT_RISK" | "NOT_APPLICABLE"; note: string; sort_order: number;
}
interface DependentRow { action_id: number; milestone_id: number; milestone_code: string; milestone_name: string; milestone_date: string; status: string }
interface HistoryRow { id: number; action: string; username: string; detail: string; result: string; at: string }

const STATUS_LABEL: Record<string, string> = { ON_TRACK: "Đúng tiến độ", AT_RISK: "Cần chú ý", BEHIND: "Trễ hạn" };
const STATUS_CLS: Record<string, string> = { ON_TRACK: "bg-emerald-100 text-emerald-700", AT_RISK: "bg-amber-100 text-amber-700", BEHIND: "bg-red-100 text-red-700" };
const ACTION_STATUS_LABEL: Record<string, string> = { COMPLETED: "Hoàn thành", NOT_COMPLETED: "Chưa hoàn thành", AT_RISK: "Cảnh báo trễ hạn", NOT_APPLICABLE: "Không đủ điều kiện" };
const ACTION_STATUS_CLS: Record<string, string> = { COMPLETED: "bg-emerald-100 text-emerald-700", NOT_COMPLETED: "bg-amber-100 text-amber-700", AT_RISK: "bg-red-100 text-red-700", NOT_APPLICABLE: "bg-slate-200 text-slate-500" };

const Notice = ({ msg }: { msg: Msg }) => (msg ? <p className={`mb-3 rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p> : null);

type Layout = "HORIZONTAL" | "THREED" | "VERTICAL";
type WindowTime = "ALL" | "YEAR";
type PageMode = "FULL" | "PAGED";
const HORIZONTAL_PAGE_SIZE = 5;
const THREED_PAGE_SIZE = 4; // recipe §8: mỗi trang 3D chỉ vài milestone để card đủ lớn/dễ đọc

/** WF-01/01B/01C/02/03 (ROADMAP_APPROVED_WIREFRAME_SPEC.md + ROADMAP_3D_IMPLEMENTATION_RECIPE.md):
 * CEO Roadmap — Horizontal/3D/Vertical View (1 data contract dùng chung `ceo-view`) + Edit Mode + Milestone Detail.
 * 3D là CSS-perspective 2.5D thuần DOM (không Three.js), Presentation Mode only — không kéo/sửa trong 3D.
 * Setup&Data hub, Data Sources, Demo Mode, 5 nhóm đo lường, Kế hoạch hành động Gantt là phần tiếp theo. */
export default function CeoRoadmap({ perm }: { perm: { manage: boolean } }) {
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([]);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [view, setView] = useState<CeoView | null>(null);
  const [activeCats, setActiveCats] = useState<Set<string>>(new Set());
  const [editMode, setEditMode] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [layout, setLayout] = useState<Layout>("HORIZONTAL");
  const [windowTime, setWindowTime] = useState<WindowTime>("ALL");
  const [pageMode, setPageMode] = useState<PageMode>("FULL");
  const [page, setPage] = useState(0);

  const loadScenarios = useCallback(async () => {
    const list = (await api.get<ScenarioRow[]>(`${RES}/scenarios`)).data;
    const withVersions = await Promise.all(list.map(async (s) => (await api.get<ScenarioRow>(`${RES}/scenarios/${s.id}`)).data));
    setScenarios(withVersions);
    if (versionId === null) {
      for (const s of withVersions) {
        const v = (s.versions ?? [])[0];
        if (v) { setVersionId(v.id); break; }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const loadView = useCallback(async () => {
    if (versionId === null) return;
    try { setView((await api.get<CeoView>(`${RES}/versions/${versionId}/ceo-view`)).data); }
    catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  }, [versionId]);
  useEffect(() => { api.get<Category[]>(`${RES}/categories`).then((r) => setCategories(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) })); void loadScenarios(); }, [loadScenarios]);
  useEffect(() => { void loadView(); }, [loadView]);

  const toggleCat = (code: string) => setActiveCats((prev) => { const n = new Set(prev); if (n.has(code)) n.delete(code); else n.add(code); return n; });
  const dimmed = (code: string | null) => activeCats.size > 0 && (!code || !activeCats.has(code));
  useEffect(() => { setPage(0); }, [layout, windowTime, pageMode, versionId]);

  const thisYear = new Date().getFullYear();
  const filtered = view ? view.milestones.filter((m) => windowTime === "ALL" || new Date(m.target_date).getFullYear() === thisYear) : [];
  const paginating = pageMode === "PAGED" && layout !== "VERTICAL";
  const pageSize = layout === "THREED" ? THREED_PAGE_SIZE : HORIZONTAL_PAGE_SIZE;
  const pageCount = paginating ? Math.max(1, Math.ceil(filtered.length / pageSize)) : 1;
  const curPage = Math.min(page, pageCount - 1);
  const shown = paginating ? filtered.slice(curPage * pageSize, curPage * pageSize + pageSize) : filtered;
  const isLastPage = curPage >= pageCount - 1;
  const summaryCard = view && view.summary.length > 0 && isLastPage ? (
    <div className="relative z-10 w-[230px] shrink-0 rounded-2xl bg-gradient-to-br from-teal-600 to-teal-500 p-3 text-white shadow-sm" data-testid="ceo-roadmap-summary">
      <div className="text-[11px] uppercase tracking-wide text-teal-100">Mục tiêu tổng</div>
      <div className="mt-2 space-y-1.5">
        {view.summary.map((s) => (
          <div key={s.category_code} className="flex items-center justify-between rounded-lg bg-white/15 px-2 py-1 text-xs">
            <span>{s.category_name}</span>
            <span className="font-bold">{s.avg_progress_percent === null ? "—" : `${Math.round(s.avg_progress_percent)}%`}</span>
          </div>
        ))}
      </div>
    </div>
  ) : null;
  const PageNav = paginating && pageCount > 1 ? (
    <div className="mt-2 flex items-center justify-center gap-3 text-xs" data-testid="ceo-roadmap-pagenav">
      <button className={btn} disabled={curPage === 0} onClick={() => setPage(curPage - 1)}>‹</button>
      <span>Trang {curPage + 1} / {pageCount}</span>
      <button className={btn} disabled={curPage >= pageCount - 1} onClick={() => setPage(curPage + 1)}>›</button>
    </div>
  ) : null;

  return (
    <div className="space-y-3">
      <div>
        <h1 className="text-xl font-bold">CEO ROADMAP</h1>
        <p className="text-xs text-slate-500">Lộ trình mục tiêu theo danh mục (Doanh số/Chất lượng/OPEX/Digital Transformation/HR). Bấm cột mốc để xem chi tiết & kế hoạch hành động; ⚙ Edit Mode để thêm/dời thời gian/xoá.</p>
      </div>
      <Notice msg={msg} />
      <div className="flex flex-wrap items-center gap-2">
        <select className={inp + " w-auto"} value={versionId ?? ""} onChange={(e) => setVersionId(Number(e.target.value) || null)}>
          <option value="">— Chọn version —</option>
          {scenarios.flatMap((s) => (s.versions ?? []).map((v) => <option key={v.id} value={v.id}>{s.name} · v{v.version_no} ({v.status})</option>))}
        </select>
        <select className={inp + " w-auto"} value={windowTime} onChange={(e) => setWindowTime(e.target.value as WindowTime)} data-testid="ceo-roadmap-window">
          <option value="ALL">Toàn trình</option>
          <option value="YEAR">Năm nay ({thisYear})</option>
        </select>
        {layout !== "VERTICAL" && (
          <select className={inp + " w-auto"} value={pageMode} onChange={(e) => setPageMode(e.target.value as PageMode)} data-testid="ceo-roadmap-pagemode">
            <option value="FULL">Toàn trình (không phân trang)</option>
            <option value="PAGED">Phân trang ({pageSize}/trang)</option>
          </select>
        )}
        <div className="flex rounded-full border border-slate-300 p-0.5 text-xs">
          {([["HORIZONTAL", "Ngang"], ["THREED", "3D"], ["VERTICAL", "Dọc"]] as [Layout, string][]).map(([v, label]) => (
            <button key={v} onClick={() => setLayout(v)} className={`rounded-full px-3 py-1 ${layout === v ? "bg-slate-900 text-white" : "text-slate-500"}`} data-testid={`ceo-roadmap-layout-${v}`}>{label}</button>
          ))}
        </div>
        <span className="flex-1" />
        <button onClick={() => setSetupOpen(true)} className={btn} title="Thiết lập & dữ liệu" data-testid="ceo-roadmap-setup">⚙ Thiết lập &amp; dữ liệu</button>
        {perm.manage && <button onClick={() => setEditMode((v) => !v)} className={editMode ? primary : btn} data-testid="ceo-roadmap-edit-toggle">{editMode ? "Đang Edit Mode — Xong" : "Edit Mode"}</button>}
        {editMode && perm.manage && <button onClick={() => setAddOpen(true)} className={primary} data-testid="ceo-roadmap-add">+ Milestone</button>}
      </div>
      <div className="flex flex-wrap gap-2">
        {categories.map((c) => (
          <button key={c.code} onClick={() => toggleCat(c.code)} className={`rounded-full border px-3 py-1 text-xs ${activeCats.has(c.code) ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white text-slate-600"}`} data-testid={`ceo-roadmap-cat-${c.code}`}>
            <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: c.color }} />{c.name}
          </button>
        ))}
      </div>

      {!view ? <p className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">Chưa có version nào — tạo Scenario/Version ở tab Mô phỏng kỹ thuật trước.</p> : layout === "HORIZONTAL" ? (
        <div>
          <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white p-4">
            <div className="relative flex min-w-max gap-5 pb-2 pt-6">
              <div className="absolute left-0 right-0 top-1/2 h-[3px] -translate-y-1/2 bg-gradient-to-r from-slate-200 via-slate-300 to-slate-200" />
              {shown.map((m) => (
                <button key={m.id} onClick={() => setDetailId(m.id)} className="relative z-10 w-[210px] shrink-0 rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:shadow-md" style={{ opacity: dimmed(m.category_code) ? 0.35 : 1 }} data-testid={`ceo-roadmap-ms-${m.id}`}>
                  {m.has_warning && <span className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-amber-500 text-xs font-black text-white" title={m.warning_note}>!</span>}
                  <div className="flex items-center gap-1 text-[11px] text-slate-400"><span className="inline-block h-2 w-2 rounded-full" style={{ background: m.category_color }} />{m.category_name || "Chưa phân loại"}</div>
                  <div className="mt-0.5 text-2xl font-extrabold">{m.progress_percent === null ? "—" : `${Math.round(m.progress_percent)}%`}</div>
                  <div className="text-sm font-bold leading-snug">{m.name || m.code}</div>
                  <div className="mt-1 text-[11px] text-slate-400">{dateVi(m.target_date)}</div>
                  <span className={`mt-2 inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_CLS[m.status]}`}>{STATUS_LABEL[m.status]}</span>
                </button>
              ))}
              {summaryCard}
            </div>
          </div>
          {PageNav}
        </div>
      ) : layout === "THREED" ? (
        <div>
          <div className="rounded-2xl border border-slate-200 bg-gradient-to-b from-white to-sky-50 p-4" data-testid="ceo-roadmap-3d">
            <div style={{ perspective: 1400, perspectiveOrigin: "50% 30%", overflow: "hidden", height: 380, position: "relative" }}>
              <div style={{ position: "absolute", left: 0, top: 0, width: Math.max(700, 40 + shown.length * 220 + 230), height: 340, transformStyle: "preserve-3d", transform: "rotateX(58deg) rotateZ(-8deg)", transformOrigin: "20% 60%" }}>
                {shown.map((m, i) => {
                  const x = 40 + i * 220 + (i % 2 === 0 ? -30 : 30);
                  const y = 40 + i * 40;
                  const z = -i * 120;
                  const scale = Math.max(0.82, 1 - i * 0.04);
                  const opacity = Math.max(0.68, 1 - i * 0.06);
                  return (
                    <button
                      key={m.id} onClick={() => setDetailId(m.id)} data-testid={`ceo-roadmap-3d-ms-${m.id}`}
                      aria-label={`${m.category_name || "Chưa phân loại"}, ${m.name || m.code}, ${dateVi(m.target_date)}, ${m.progress_percent === null ? "chưa có tiến độ" : `${Math.round(m.progress_percent)} phần trăm`}, ${STATUS_LABEL[m.status]}${m.has_warning ? ", cần chú ý" : ""}`}
                      style={{ position: "absolute", left: 0, top: 0, width: 190, transform: `translate3d(${x}px, ${y}px, ${z}px) rotateZ(8deg) rotateX(-58deg) scale(${scale})`, opacity: dimmed(m.category_code) ? opacity * 0.4 : opacity, transformStyle: "preserve-3d" }}
                      className="rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-xl"
                    >
                      {m.has_warning && <span className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-amber-500 text-xs font-black text-white">!</span>}
                      <div className="flex items-center gap-1 text-[11px] text-slate-400"><span className="inline-block h-2 w-2 rounded-full" style={{ background: m.category_color }} />{m.category_name || "Chưa phân loại"}</div>
                      <div className="mt-0.5 text-xl font-extrabold">{m.progress_percent === null ? "—" : `${Math.round(m.progress_percent)}%`}</div>
                      <div className="text-sm font-bold leading-snug">{m.name || m.code}</div>
                      <div className="mt-1 text-[11px] text-slate-400">{dateVi(m.target_date)}</div>
                    </button>
                  );
                })}
              </div>
            </div>
            <p className="mt-2 text-[11px] text-slate-400">3D là chế độ trình bày (xem/lọc/phân trang) — kéo thả/sửa vẫn thực hiện ở layout Ngang khi bật Edit Mode.</p>
          </div>
          {PageNav}
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-white p-4" data-testid="ceo-roadmap-vertical">
          <div className="relative space-y-4 pl-9">
            <div className="absolute bottom-2 left-[15px] top-2 w-[3px] bg-slate-200" />
            {filtered.map((m) => (
              <button key={m.id} onClick={() => setDetailId(m.id)} className="relative block w-full rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm" style={{ opacity: dimmed(m.category_code) ? 0.35 : 1 }} data-testid={`ceo-roadmap-v-ms-${m.id}`}>
                <span className="absolute -left-[27px] top-4 h-4 w-4 rounded-full border-2 border-white shadow" style={{ background: m.category_color }} />
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-[11px] text-slate-400">{dateVi(m.target_date)} · {m.category_name || "Chưa phân loại"}</div>
                  {m.has_warning && <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-[10px] font-black text-white" title={m.warning_note}>!</span>}
                </div>
                <div className="mt-1 text-sm font-bold">{m.name || m.code}</div>
                <div className="mt-1 flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_CLS[m.status]}`}>{STATUS_LABEL[m.status]}</span>
                  <span className="text-xs text-slate-400">{m.progress_percent === null ? "—" : `${Math.round(m.progress_percent)}%`}</span>
                </div>
              </button>
            ))}
            {filtered.length === 0 && <p className="py-4 text-center text-xs text-slate-400">Không có milestone trong khoảng thời gian này.</p>}
          </div>
          {view.summary.length > 0 && (
            <div className="mt-4 rounded-2xl bg-gradient-to-br from-teal-600 to-teal-500 p-3 text-white">
              <div className="text-[11px] uppercase tracking-wide text-teal-100">Mục tiêu tổng</div>
              <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                {view.summary.map((s) => (
                  <div key={s.category_code} className="flex items-center justify-between rounded-lg bg-white/15 px-2 py-1 text-xs">
                    <span>{s.category_name}</span>
                    <span className="font-bold">{s.avg_progress_percent === null ? "—" : `${Math.round(s.avg_progress_percent)}%`}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {addOpen && versionId !== null && <AddMilestoneModal versionId={versionId} categories={categories} onClose={() => setAddOpen(false)} onDone={() => { setAddOpen(false); void loadView(); }} setMsg={setMsg} />}
      {detailId !== null && <DetailModal milestoneId={detailId} milestones={view?.milestones ?? []} editMode={editMode} categories={categories} onClose={() => setDetailId(null)} onChanged={() => void loadView()} setMsg={setMsg} />}
      {setupOpen && <SetupHubModal perm={perm} categories={categories} onClose={() => setSetupOpen(false)} onCategoriesChanged={() => api.get<Category[]>(`${RES}/categories`).then((r) => setCategories(r.data))} setMsg={setMsg} />}
    </div>
  );
}

function AddMilestoneModal({ versionId, categories, onClose, onDone, setMsg }: { versionId: number; categories: Category[]; onClose: () => void; onDone: () => void; setMsg: (m: Msg) => void }) {
  const [d, setD] = useState({ code: "", name: "", target_date: "", category_code: categories[0]?.code ?? "" });
  const submit = async () => {
    try {
      const m = await api.post<{ id: number }>(`${RES}/versions/${versionId}/milestones`, { code: d.code, name: d.name, target_date: d.target_date, sequence: Date.now() % 100000 });
      if (d.category_code) await api.put(`${RES}/milestones/${m.data.id}/ceo-fields`, { category_code: d.category_code });
      setMsg({ ok: true, text: "Đã thêm milestone (Draft)." });
      onDone();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl bg-white p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-3 text-lg font-bold">+ Milestone</h3>
        <div className="space-y-2">
          <label className="block text-xs text-slate-500">Mã<input className={inp} value={d.code} onChange={(e) => setD({ ...d, code: e.target.value })} /></label>
          <label className="block text-xs text-slate-500">Tên<input className={inp} value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></label>
          <label className="block text-xs text-slate-500">Ngày mục tiêu<input type="date" className={inp} value={d.target_date} onChange={(e) => setD({ ...d, target_date: e.target.value })} /></label>
          <label className="block text-xs text-slate-500">Danh mục
            <select className={inp} value={d.category_code} onChange={(e) => setD({ ...d, category_code: e.target.value })}>
              {categories.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select>
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2"><button className={btn} onClick={onClose}>Huỷ</button><button className={primary} disabled={!d.code || !d.target_date} onClick={() => void submit()}>Thêm</button></div>
      </div>
    </div>
  );
}

const DETAIL_TABS = ["Tổng quan", "Tiến độ & Kết quả", "Kế hoạch hành động", "Bằng chứng", "Phụ thuộc/liên kết", "Lịch sử"] as const;
type DetailTab = typeof DETAIL_TABS[number];
const ACTION_BAR_PCT: Record<string, number> = { COMPLETED: 100, AT_RISK: 60, NOT_COMPLETED: 40, NOT_APPLICABLE: 0 };
const ACTION_BAR_CLS: Record<string, string> = { COMPLETED: "bg-emerald-500", AT_RISK: "bg-red-500", NOT_COMPLETED: "bg-amber-400", NOT_APPLICABLE: "bg-slate-300" };

function DetailModal({ milestoneId, milestones, editMode, categories, onClose, onChanged, setMsg }: {
  milestoneId: number; milestones: MilestoneCard[]; editMode: boolean; categories: Category[]; onClose: () => void; onChanged: () => void; setMsg: (m: Msg) => void;
}) {
  const m = milestones.find((x) => x.id === milestoneId) ?? null;
  const [tab, setTab] = useState<DetailTab>("Tổng quan");
  const [actions, setActions] = useState<ActionRow[]>([]);
  const [dependents, setDependents] = useState<DependentRow[] | null>(null);
  const [history, setHistory] = useState<HistoryRow[] | null>(null);
  const [addingAction, setAddingAction] = useState(false);
  const loadActions = useCallback(async () => setActions((await api.get<ActionRow[]>(`${RES}/milestones/${milestoneId}/actions`)).data), [milestoneId]);
  useEffect(() => { void loadActions(); }, [loadActions]);
  useEffect(() => {
    if (tab === "Phụ thuộc/liên kết" && dependents === null) void api.get<DependentRow[]>(`${RES}/milestones/${milestoneId}/dependents`).then((r) => setDependents(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
    if (tab === "Lịch sử" && history === null) void api.get<HistoryRow[]>(`${RES}/milestones/${milestoneId}/history`).then((r) => setHistory(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, milestoneId]);

  const setField = async (patch: Record<string, unknown>) => {
    try { await api.put(`${RES}/milestones/${milestoneId}/ceo-fields`, patch); onChanged(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const del = async () => {
    if (!confirm("Xoá milestone này?")) return;
    try { await api.delete(`${RES}/milestones/${milestoneId}`); setMsg({ ok: true, text: "Đã xoá milestone." }); onChanged(); onClose(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };

  const receivedLinks = actions.filter((a) => a.action_type === "MILESTONE_LINK");
  const plainActions = actions.filter((a) => a.action_type === "ACTION");

  if (!m) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4" onClick={onClose}>
      <div className="my-4 w-full max-w-2xl rounded-2xl bg-white p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <span className="rounded-full px-2 py-0.5 text-[11px]" style={{ background: `${m.category_color}22`, color: m.category_color }}>{m.category_name || "Chưa phân loại"}</span>
          <div className="text-base font-bold">{m.name || m.code}</div>
          <span className="flex-1" />
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕ Đóng</button>
        </div>
        <div className="mt-1 text-xs text-slate-400">Milestone · Ngày mục tiêu {dateVi(m.target_date)}</div>

        <div className="mt-3 flex flex-wrap gap-1 border-b border-slate-200">
          {DETAIL_TABS.map((t) => (
            <button key={t} onClick={() => setTab(t)} className={`rounded-t-lg px-3 py-1.5 text-xs font-semibold ${tab === t ? "bg-slate-900 text-white" : "text-slate-500 hover:bg-slate-100"}`} data-testid={`ceo-detail-tab-${t}`}>{t}</button>
          ))}
        </div>

        {tab === "Tổng quan" && (
          editMode ? (
            <div className="mt-4 space-y-3">
              <div className="grid grid-cols-2 gap-3 rounded-xl border border-slate-200 p-3">
                <label className="block text-xs text-slate-500">Danh mục
                  <select className={inp} value={m.category_code ?? ""} onChange={(e) => void setField({ category_code: e.target.value || null })}>
                    <option value="">—</option>
                    {categories.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                  </select>
                </label>
                <label className="block text-xs text-slate-500">Nguồn đo lường (WF-04)
                  <select className={inp} value={m.measurement_family} onChange={(e) => void setField({ measurement_family: e.target.value })}>
                    {Object.entries(MEASUREMENT_FAMILY_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </label>
                {m.measurement_family === "OPERATIONAL" ? (
                  <>
                    <label className="block text-xs text-slate-500">Chỉ tiêu
                      <select className={inp} value={m.measurement_metric_code ?? ""} onChange={(e) => void setField({ measurement_metric_code: e.target.value })}>
                        <option value="">—</option>
                        <option value="REVENUE">Doanh thu (REVENUE)</option>
                        <option value="OUTPUT_QTY">Sản lượng đóng gói (OUTPUT_QTY)</option>
                      </select>
                    </label>
                    <label className="block text-xs text-slate-500">Kỳ
                      <div className="flex gap-1">
                        <select className={inp} value={m.measurement_period_type} onChange={(e) => void setField({ measurement_period_type: e.target.value })}>
                          <option value="MONTH">Tháng</option><option value="YEAR">Năm</option>
                        </select>
                        <input type="number" className={inp} placeholder="Năm" defaultValue={m.measurement_period_year ?? ""} onBlur={(e) => e.target.value !== "" && void setField({ measurement_period_year: Number(e.target.value) })} />
                        {m.measurement_period_type === "MONTH" && <input type="number" min={1} max={12} className={inp} placeholder="Tháng" defaultValue={m.measurement_period_month ?? ""} onBlur={(e) => e.target.value !== "" && void setField({ measurement_period_month: Number(e.target.value) })} />}
                      </div>
                    </label>
                    <label className="block text-xs text-slate-500">Phạm vi
                      <select className={inp} value={m.measurement_scope_type} onChange={(e) => void setField({ measurement_scope_type: e.target.value })}>
                        <option value="TOTAL">Tổng công ty</option><option value="FACTORY">Theo XN (chỉ REVENUE)</option>
                      </select>
                    </label>
                    <label className="block text-xs text-slate-500">Mục tiêu (số)<input type="number" className={inp} defaultValue={m.measurement_target_value ?? ""} onBlur={(e) => e.target.value !== "" && void setField({ measurement_target_value: Number(e.target.value) })} /></label>
                    <p className="col-span-2 text-[11px] text-amber-700">Progress/Baseline/Gap sẽ TỰ TÍNH từ dữ liệu thật (revenue_monthly/yearly, po_pack_daily) — không nhập tay được nữa khi chọn Operational Data.</p>
                  </>
                ) : (
                  <label className="block text-xs text-slate-500">Tiến độ %<input type="number" min={0} max={100} className={inp} defaultValue={m.progress_percent ?? ""} onBlur={(e) => e.target.value !== "" && void setField({ progress_percent: Number(e.target.value) })} /></label>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3 rounded-xl border border-slate-200 p-3">
                <label className="col-span-2 block text-xs text-slate-500">Hiện trạng / Baseline{m.measurement_family === "OPERATIONAL" ? <input className={inp} value={m.baseline_label} disabled /> : <input className={inp} defaultValue={m.baseline_label} onBlur={(e) => void setField({ baseline_label: e.target.value })} />}</label>
                <label className="col-span-2 block text-xs text-slate-500">Gap / Khoảng thiếu{m.measurement_family === "OPERATIONAL" ? <input className={inp} value={m.gap_label} disabled /> : <input className={inp} defaultValue={m.gap_label} onBlur={(e) => void setField({ gap_label: e.target.value })} />}</label>
                <label className="col-span-2 block text-xs text-slate-500">Phương án đề xuất<textarea className={inp} rows={2} defaultValue={m.proposal_summary} onBlur={(e) => void setField({ proposal_summary: e.target.value })} /></label>
                <label className="col-span-2 block text-xs text-slate-500">Ghi chú cảnh báo (rỗng = không cảnh báo)<input className={inp} defaultValue={m.warning_note} onBlur={(e) => void setField({ warning_note: e.target.value })} /></label>
              </div>
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 p-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-bold">{m.name || m.code}</div>
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_CLS[m.status]}`}>{STATUS_LABEL[m.status]}</span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-3 border-t border-sky-200 pt-2 text-xs">
                <div><div className="font-semibold text-slate-500">Hiện trạng / Baseline</div><div className="mt-0.5">{m.baseline_label || "—"}</div></div>
                <div><div className="font-semibold text-slate-500">Gap / Khoảng thiếu</div><div className="mt-0.5">{m.gap_label || "—"}</div></div>
                <div><div className="font-semibold text-slate-500">Phương án đề xuất</div><div className="mt-0.5">{m.proposal_summary || "—"}</div></div>
              </div>
            </div>
          )
        )}

        {tab === "Tiến độ & Kết quả" && (
          <div className="mt-4 space-y-3">
            <div className="rounded-xl border border-slate-200 p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="font-semibold">Tiến độ hiện tại</span>
                <span className="text-lg font-extrabold">{m.progress_percent === null ? "—" : `${Math.round(m.progress_percent)}%`}</span>
              </div>
              <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-sky-500" style={{ width: `${m.progress_percent ?? 0}%` }} /></div>
              <div className="mt-2 flex items-center gap-2 text-xs">
                <span className={`rounded-full px-2 py-0.5 font-semibold ${STATUS_CLS[m.status]}`}>{STATUS_LABEL[m.status]}</span>
                {m.has_warning && <span className="text-amber-700">⚠ {m.warning_note}</span>}
              </div>
            </div>
            <p className="text-[11px] text-slate-400">Nguồn đo lường: <b>{MEASUREMENT_FAMILY_LABEL[m.measurement_family]}</b>{m.measurement_family === "OPERATIONAL" && m.measurement_metric_code ? ` · ${m.measurement_metric_code} · ${m.measurement_period_type === "MONTH" ? `${m.measurement_period_month}/${m.measurement_period_year}` : m.measurement_period_year}` : ""}. Đổi ở tab Tổng quan (Edit Mode). Financial/OPEX, Machine Data, QA (chiều giảm lỗi) để phase sau.</p>
          </div>
        )}

        {tab === "Kế hoạch hành động" && (
          <div className="mt-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-bold">Hành động</div>
              {editMode && <button className={btn} onClick={() => setAddingAction(true)}>+ Thêm</button>}
            </div>
            <p className="text-[11px] text-amber-700">Mỗi dòng là "Action" (việc rời) hoặc "Milestone" (tham chiếu 1 milestone TRƯỚC ĐÓ dùng làm điều kiện).</p>
            <div className="mt-2 space-y-1.5">
              {actions.map((a) => (
                <div key={a.id} className="border-b border-slate-100 py-1.5">
                  <div className="flex items-center gap-2 text-xs">
                    <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${a.action_type === "MILESTONE_LINK" ? "bg-sky-100 text-sky-700" : "bg-slate-200 text-slate-600"}`}>{a.action_type === "MILESTONE_LINK" ? "MILESTONE" : "ACTION"}</span>
                    <span className="flex-1">{a.title}{a.action_type === "MILESTONE_LINK" && <span className="text-slate-400"> · {a.ref_milestone_code} {a.ref_milestone_date ? dateVi(a.ref_milestone_date) : ""}</span>}</span>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${ACTION_STATUS_CLS[a.status]}`}>{ACTION_STATUS_LABEL[a.status]}</span>
                    {editMode && <button className="text-red-500" onClick={() => void api.delete(`${RES}/milestone-actions/${a.id}`).then(() => loadActions())}>✕</button>}
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${ACTION_BAR_CLS[a.status]}`} style={{ width: `${ACTION_BAR_PCT[a.status]}%` }} /></div>
                </div>
              ))}
              {actions.length === 0 && <p className="py-2 text-center text-xs text-slate-400">Chưa có hành động nào.</p>}
            </div>
            {addingAction && <AddActionForm milestoneId={milestoneId} milestones={milestones} onClose={() => setAddingAction(false)} onDone={() => { setAddingAction(false); void loadActions(); }} setMsg={setMsg} />}
          </div>
        )}

        {tab === "Bằng chứng" && (
          <div className="mt-4 rounded-xl border border-dashed border-slate-300 p-4 text-center text-xs text-slate-400">
            Minh chứng &amp; phân tích đề xuất — để phân tích sau (theo spec, chưa thiết kế cụ thể ở Phase 1).
          </div>
        )}

        {tab === "Phụ thuộc/liên kết" && (
          <div className="mt-4 space-y-3 text-xs">
            <div>
              <div className="font-semibold text-slate-500">▶ Là tiền đề cho (chiều đi)</div>
              {dependents === null ? <p className="mt-1 text-slate-400">Đang tải…</p> : dependents.length === 0 ? <p className="mt-1 text-slate-400">(chưa có)</p> : (
                <div className="mt-1 space-y-1">
                  {dependents.map((d) => (
                    <div key={d.action_id} className="flex items-center justify-between rounded-lg border border-slate-100 px-2 py-1">
                      <span>{d.milestone_name || d.milestone_code} · {dateVi(d.milestone_date)}</span>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${ACTION_STATUS_CLS[d.status]}`}>{ACTION_STATUS_LABEL[d.status]}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <div className="font-semibold text-slate-500">◀ Nhận điều kiện từ (chiều vào)</div>
              {receivedLinks.length === 0 ? <p className="mt-1 text-slate-400">(chưa có)</p> : (
                <div className="mt-1 space-y-1">
                  {receivedLinks.map((a) => (
                    <div key={a.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-2 py-1">
                      <span>{a.ref_milestone_code} · {a.ref_milestone_date ? dateVi(a.ref_milestone_date) : ""}</span>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${ACTION_STATUS_CLS[a.status]}`}>{ACTION_STATUS_LABEL[a.status]}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {plainActions.length > 0 && <p className="text-slate-400">({plainActions.length} action tự do không phải liên kết milestone — xem tab Kế hoạch hành động)</p>}
          </div>
        )}

        {tab === "Lịch sử" && (
          <div className="mt-4 text-xs">
            {history === null ? <p className="text-slate-400">Đang tải…</p> : history.length === 0 ? <p className="text-slate-400">Chưa có lịch sử thay đổi.</p> : (
              <div className="space-y-1.5">
                {history.map((h) => (
                  <div key={h.id} className="flex items-center justify-between border-b border-slate-100 py-1.5">
                    <div><span className="font-semibold">{h.action}</span><span className="ml-2 text-slate-400">{h.detail}</span></div>
                    <div className="text-slate-400">{h.username} · {new Date(h.at).toLocaleString("vi-VN")}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {editMode && <div className="mt-5 flex justify-end"><button className="text-xs text-red-500 hover:underline" onClick={() => void del()}>Xoá milestone</button></div>}
      </div>
    </div>
  );
}

function AddActionForm({ milestoneId, milestones, onClose, onDone, setMsg }: { milestoneId: number; milestones: MilestoneCard[]; onClose: () => void; onDone: () => void; setMsg: (m: Msg) => void }) {
  const priorOptions = milestones.filter((x) => x.id !== milestoneId);
  const [d, setD] = useState({ action_type: "ACTION" as "ACTION" | "MILESTONE_LINK", title: "", ref_milestone_id: priorOptions[0]?.id ?? 0 });
  const submit = async () => {
    try {
      await api.post(`${RES}/milestones/${milestoneId}/actions`, { action_type: d.action_type, title: d.title, ref_milestone_id: d.action_type === "MILESTONE_LINK" ? d.ref_milestone_id : undefined });
      onDone();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="flex gap-2 text-xs">
        <button className={`rounded-full px-3 py-1 ${d.action_type === "ACTION" ? "bg-slate-900 text-white" : "border border-slate-300 bg-white"}`} onClick={() => setD({ ...d, action_type: "ACTION" })}>Action</button>
        <button className={`rounded-full px-3 py-1 ${d.action_type === "MILESTONE_LINK" ? "bg-slate-900 text-white" : "border border-slate-300 bg-white"}`} onClick={() => setD({ ...d, action_type: "MILESTONE_LINK" })}>Milestone (tham chiếu)</button>
      </div>
      {d.action_type === "ACTION" ? (
        <input className={inp + " mt-2"} placeholder="Tên hành động" value={d.title} onChange={(e) => setD({ ...d, title: e.target.value })} />
      ) : (
        <select className={inp + " mt-2"} value={d.ref_milestone_id} onChange={(e) => setD({ ...d, ref_milestone_id: Number(e.target.value) })}>
          {priorOptions.map((o) => <option key={o.id} value={o.id}>{o.name || o.code} · {dateVi(o.target_date)}</option>)}
        </select>
      )}
      <div className="mt-2 flex justify-end gap-2"><button className={btn} onClick={onClose}>Huỷ</button><button className={primary} onClick={() => void submit()}>Lưu</button></div>
    </div>
  );
}

interface DataSourceRow { source: string; data: string; cycle: string; last_sync: string | null; last_status?: string; status: string; status_label: string }
const DS_STATUS_CLS: Record<string, string> = { HEALTHY: "bg-emerald-100 text-emerald-700", STALE: "bg-amber-100 text-amber-700", MANUAL: "bg-sky-100 text-sky-700", NOT_INTEGRATED: "bg-slate-200 text-slate-500" };

const SETUP_GROUPS = [
  { key: "targets", title: "Định nghĩa mục tiêu", desc: "Danh mục (category) dùng để phân loại milestone trên Roadmap." },
  { key: "capacity", title: "Định mức năng lực", desc: "Chuẩn năng lực lao động/máy móc — chưa triển khai ở Phase 1 (xem Rule thực thi ở tab Mô phỏng kỹ thuật)." },
  { key: "machine", title: "Máy móc & công nghệ", desc: "Machine Registry, model mapping, Future Technology — xem trang Nguồn lực / Công nghệ tương lai." },
  { key: "cost", title: "Chi phí & căn cứ", desc: "Cost evidence cho mô phỏng đầu tư — xem \"Cost Evidence\" ở tab Mô phỏng kỹ thuật." },
  { key: "sources", title: "Nguồn dữ liệu", desc: "Trạng thái đồng bộ/mapping các nguồn dữ liệu thật của hệ thống." },
  { key: "approval", title: "Quyền duyệt & lịch sử", desc: "Phân quyền roadmap.manage/run/approve — xem trang Quản trị." },
  { key: "demo", title: "Dữ liệu demo", desc: "Tạo/reset dữ liệu demo có seed cố định — để Phase sau." },
] as const;
type SetupKey = typeof SETUP_GROUPS[number]["key"];

function SetupHubModal({ perm, categories, onClose, onCategoriesChanged, setMsg }: { perm: { manage: boolean }; categories: Category[]; onClose: () => void; onCategoriesChanged: () => void; setMsg: (m: Msg) => void }) {
  const [open, setOpen] = useState<SetupKey | null>(null);
  const [sources, setSources] = useState<DataSourceRow[] | null>(null);
  useEffect(() => { if (open === "sources" && sources === null) void api.get<DataSourceRow[]>(`${RES}/data-sources`).then((r) => setSources(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [open, sources, setMsg]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4" onClick={onClose}>
      <div className="my-4 w-full max-w-3xl rounded-2xl bg-white p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold">⚙ Thiết lập &amp; dữ liệu</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕ Đóng</button>
        </div>
        {open === null ? (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            {SETUP_GROUPS.map((g) => (
              <button key={g.key} onClick={() => setOpen(g.key)} className="rounded-2xl border border-slate-200 p-4 text-left hover:border-slate-400" data-testid={`ceo-setup-${g.key}`}>
                <div className="text-sm font-bold">{g.title}</div>
                <p className="mt-1 text-[11px] text-slate-500">{g.desc}</p>
                <span className="mt-3 inline-block text-xs font-semibold text-sky-600">Mở cấu hình →</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="mt-4">
            <button onClick={() => setOpen(null)} className="text-xs text-slate-400 hover:text-slate-700">← Tất cả nhóm</button>
            <h4 className="mt-2 text-sm font-bold">{SETUP_GROUPS.find((g) => g.key === open)?.title}</h4>

            {open === "targets" && <CategoryManagerPanel categories={categories} perm={perm} onChanged={onCategoriesChanged} setMsg={setMsg} />}

            {open === "sources" && (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-[11px] uppercase text-slate-400"><th className="py-1.5">Nguồn</th><th>Dữ liệu</th><th>Chu kỳ</th><th>Last Sync</th><th>Trạng thái</th></tr></thead>
                  <tbody>
                    {(sources ?? []).map((s) => (
                      <tr key={s.source} className="border-t border-slate-100">
                        <td className="py-1.5 font-semibold">{s.source}</td>
                        <td>{s.data}</td>
                        <td>{s.cycle}</td>
                        <td>{s.last_sync ? new Date(s.last_sync).toLocaleString("vi-VN") : "—"}</td>
                        <td><span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${DS_STATUS_CLS[s.status]}`}>{s.status_label}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {sources === null && <p className="py-3 text-center text-slate-400">Đang tải…</p>}
              </div>
            )}

            {(open === "capacity" || open === "machine" || open === "cost" || open === "approval" || open === "demo") && (
              <p className="mt-3 rounded-xl border border-dashed border-slate-300 p-4 text-xs text-slate-400">{SETUP_GROUPS.find((g) => g.key === open)?.desc}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function CategoryManagerPanel({ categories, perm, onChanged, setMsg }: { categories: Category[]; perm: { manage: boolean }; onChanged: () => void; setMsg: (m: Msg) => void }) {
  const [adding, setAdding] = useState(false);
  const [d, setD] = useState({ code: "", name: "", color: "#2563eb" });
  const save = async (id: number, patch: Record<string, unknown>) => {
    try { await api.put(`${RES}/categories/${id}`, patch); onChanged(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const create = async () => {
    try { await api.post(`${RES}/categories`, d); setD({ code: "", name: "", color: "#2563eb" }); setAdding(false); onChanged(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  return (
    <div className="mt-3 space-y-2 text-xs">
      {categories.map((c) => (
        <div key={c.id} className="flex items-center gap-2 rounded-lg border border-slate-100 px-2 py-1.5">
          <input type="color" defaultValue={c.color} disabled={!perm.manage} onBlur={(e) => void save(c.id, { color: e.target.value })} className="h-6 w-6 rounded" />
          <input className={inp + " flex-1"} defaultValue={c.name} disabled={!perm.manage} onBlur={(e) => e.target.value !== c.name && void save(c.id, { name: e.target.value })} />
          <label className="flex items-center gap-1 text-[11px] text-slate-500"><input type="checkbox" defaultChecked={c.active} disabled={!perm.manage} onChange={(e) => void save(c.id, { active: e.target.checked })} />Hiện</label>
        </div>
      ))}
      {perm.manage && (adding ? (
        <div className="flex items-center gap-2 rounded-lg border border-dashed border-slate-300 px-2 py-1.5">
          <input className={inp} placeholder="Mã (code)" value={d.code} onChange={(e) => setD({ ...d, code: e.target.value })} />
          <input className={inp} placeholder="Tên hiển thị" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} />
          <input type="color" value={d.color} onChange={(e) => setD({ ...d, color: e.target.value })} className="h-6 w-6 rounded" />
          <button className={btn} onClick={() => setAdding(false)}>Huỷ</button>
          <button className={primary} disabled={!d.code} onClick={() => void create()}>Lưu</button>
        </div>
      ) : <button className={btn} onClick={() => setAdding(true)}>+ Category</button>)}
    </div>
  );
}
