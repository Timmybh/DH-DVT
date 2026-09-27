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
}
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

const STATUS_LABEL: Record<string, string> = { ON_TRACK: "Đúng tiến độ", AT_RISK: "Cần chú ý", BEHIND: "Trễ hạn" };
const STATUS_CLS: Record<string, string> = { ON_TRACK: "bg-emerald-100 text-emerald-700", AT_RISK: "bg-amber-100 text-amber-700", BEHIND: "bg-red-100 text-red-700" };
const ACTION_STATUS_LABEL: Record<string, string> = { COMPLETED: "Hoàn thành", NOT_COMPLETED: "Chưa hoàn thành", AT_RISK: "Cảnh báo trễ hạn", NOT_APPLICABLE: "Không đủ điều kiện" };
const ACTION_STATUS_CLS: Record<string, string> = { COMPLETED: "bg-emerald-100 text-emerald-700", NOT_COMPLETED: "bg-amber-100 text-amber-700", AT_RISK: "bg-red-100 text-red-700", NOT_APPLICABLE: "bg-slate-200 text-slate-500" };

const Notice = ({ msg }: { msg: Msg }) => (msg ? <p className={`mb-3 rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p> : null);

/** WF-01/02/03 (ROADMAP_APPROVED_WIREFRAME_SPEC.md): CEO Roadmap — Horizontal View + Edit Mode + Milestone Detail.
 * Lớp trình bày business-facing, dùng chung version/milestone của Roadmap Simulation (Task 5) làm khung thời gian.
 * 3D/Vertical layout, Setup&Data hub, Data Sources, Demo Mode là phần tiếp theo (chưa làm trong bản này). */
export default function CeoRoadmap({ perm }: { perm: { manage: boolean } }) {
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([]);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [view, setView] = useState<CeoView | null>(null);
  const [activeCats, setActiveCats] = useState<Set<string>>(new Set());
  const [editMode, setEditMode] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [msg, setMsg] = useState<Msg>(null);

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
        <span className="flex-1" />
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

      {!view ? <p className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">Chưa có version nào — tạo Scenario/Version ở tab Mô phỏng kỹ thuật trước.</p> : (
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white p-4">
          <div className="relative flex min-w-max gap-5 pb-2 pt-6">
            <div className="absolute left-0 right-0 top-1/2 h-[3px] -translate-y-1/2 bg-gradient-to-r from-slate-200 via-slate-300 to-slate-200" />
            {view.milestones.map((m) => (
              <button key={m.id} onClick={() => setDetailId(m.id)} className="relative z-10 w-[210px] shrink-0 rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:shadow-md" style={{ opacity: dimmed(m.category_code) ? 0.35 : 1 }} data-testid={`ceo-roadmap-ms-${m.id}`}>
                {m.has_warning && <span className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-amber-500 text-xs font-black text-white" title={m.warning_note}>!</span>}
                <div className="flex items-center gap-1 text-[11px] text-slate-400"><span className="inline-block h-2 w-2 rounded-full" style={{ background: m.category_color }} />{m.category_name || "Chưa phân loại"}</div>
                <div className="mt-0.5 text-2xl font-extrabold">{m.progress_percent === null ? "—" : `${Math.round(m.progress_percent)}%`}</div>
                <div className="text-sm font-bold leading-snug">{m.name || m.code}</div>
                <div className="mt-1 text-[11px] text-slate-400">{dateVi(m.target_date)}</div>
                <span className={`mt-2 inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${STATUS_CLS[m.status]}`}>{STATUS_LABEL[m.status]}</span>
              </button>
            ))}
            {view.summary.length > 0 && (
              <div className="relative z-10 w-[230px] shrink-0 rounded-2xl bg-gradient-to-br from-teal-600 to-teal-500 p-3 text-white shadow-sm">
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
            )}
          </div>
        </div>
      )}

      {addOpen && versionId !== null && <AddMilestoneModal versionId={versionId} categories={categories} onClose={() => setAddOpen(false)} onDone={() => { setAddOpen(false); void loadView(); }} setMsg={setMsg} />}
      {detailId !== null && <DetailModal milestoneId={detailId} milestones={view?.milestones ?? []} editMode={editMode} categories={categories} onClose={() => setDetailId(null)} onChanged={() => void loadView()} setMsg={setMsg} />}
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

function DetailModal({ milestoneId, milestones, editMode, categories, onClose, onChanged, setMsg }: {
  milestoneId: number; milestones: MilestoneCard[]; editMode: boolean; categories: Category[]; onClose: () => void; onChanged: () => void; setMsg: (m: Msg) => void;
}) {
  const m = milestones.find((x) => x.id === milestoneId) ?? null;
  const [actions, setActions] = useState<ActionRow[]>([]);
  const [addingAction, setAddingAction] = useState(false);
  const loadActions = useCallback(async () => setActions((await api.get<ActionRow[]>(`${RES}/milestones/${milestoneId}/actions`)).data), [milestoneId]);
  useEffect(() => { void loadActions(); }, [loadActions]);

  const setField = async (patch: Record<string, unknown>) => {
    try { await api.put(`${RES}/milestones/${milestoneId}/ceo-fields`, patch); onChanged(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const del = async () => {
    if (!confirm("Xoá milestone này?")) return;
    try { await api.delete(`${RES}/milestones/${milestoneId}`); setMsg({ ok: true, text: "Đã xoá milestone." }); onChanged(); onClose(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };

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

        {editMode ? (
          <div className="mt-4 grid grid-cols-2 gap-3 rounded-xl border border-slate-200 p-3">
            <label className="block text-xs text-slate-500">Danh mục
              <select className={inp} value={m.category_code ?? ""} onChange={(e) => void setField({ category_code: e.target.value || null })}>
                <option value="">—</option>
                {categories.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </select>
            </label>
            <label className="block text-xs text-slate-500">Tiến độ %<input type="number" min={0} max={100} className={inp} defaultValue={m.progress_percent ?? ""} onBlur={(e) => e.target.value !== "" && void setField({ progress_percent: Number(e.target.value) })} /></label>
            <label className="col-span-2 block text-xs text-slate-500">Hiện trạng / Baseline<input className={inp} defaultValue={m.baseline_label} onBlur={(e) => void setField({ baseline_label: e.target.value })} /></label>
            <label className="col-span-2 block text-xs text-slate-500">Gap / Khoảng thiếu<input className={inp} defaultValue={m.gap_label} onBlur={(e) => void setField({ gap_label: e.target.value })} /></label>
            <label className="col-span-2 block text-xs text-slate-500">Phương án đề xuất<textarea className={inp} rows={2} defaultValue={m.proposal_summary} onBlur={(e) => void setField({ proposal_summary: e.target.value })} /></label>
            <label className="col-span-2 block text-xs text-slate-500">Ghi chú cảnh báo (rỗng = không cảnh báo)<input className={inp} defaultValue={m.warning_note} onBlur={(e) => void setField({ warning_note: e.target.value })} /></label>
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
        )}

        <div className="mt-4 flex items-center justify-between">
          <div className="text-sm font-bold">Hành động</div>
          {editMode && <button className={btn} onClick={() => setAddingAction(true)}>+ Thêm</button>}
        </div>
        <p className="text-[11px] text-amber-700">Mỗi dòng là "Action" (việc rời) hoặc "Milestone" (tham chiếu 1 milestone TRƯỚC ĐÓ dùng làm điều kiện).</p>
        <div className="mt-2 space-y-1.5">
          {actions.map((a) => (
            <div key={a.id} className="flex items-center gap-2 border-b border-slate-100 py-1.5 text-xs">
              <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${a.action_type === "MILESTONE_LINK" ? "bg-sky-100 text-sky-700" : "bg-slate-200 text-slate-600"}`}>{a.action_type === "MILESTONE_LINK" ? "MILESTONE" : "ACTION"}</span>
              <span className="flex-1">{a.title}{a.action_type === "MILESTONE_LINK" && <span className="text-slate-400"> · {a.ref_milestone_code} {a.ref_milestone_date ? dateVi(a.ref_milestone_date) : ""}</span>}</span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${ACTION_STATUS_CLS[a.status]}`}>{ACTION_STATUS_LABEL[a.status]}</span>
              {editMode && <button className="text-red-500" onClick={() => void api.delete(`${RES}/milestone-actions/${a.id}`).then(() => loadActions())}>✕</button>}
            </div>
          ))}
          {actions.length === 0 && <p className="py-2 text-center text-xs text-slate-400">Chưa có hành động nào.</p>}
        </div>

        {addingAction && <AddActionForm milestoneId={milestoneId} milestones={milestones} onClose={() => setAddingAction(false)} onDone={() => { setAddingAction(false); void loadActions(); }} setMsg={setMsg} />}

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
