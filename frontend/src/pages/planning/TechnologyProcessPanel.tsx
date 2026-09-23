import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { dateVi, num } from "../../lib/format";

const RES = "/planning/technology-process";
const inp = "w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400 whitespace-nowrap";
const btn = "rounded-full border border-slate-300 px-3 py-1.5 text-xs";
const primary = "rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-40";

const LAYER_LABEL: Record<string, string> = { CURRENT_PROCESS: "Current Process", OPTIMIZED_CURRENT_TECHNOLOGY: "Optimized Current Technology", FUTURE_TECHNOLOGY: "Future Technology" };
const STATUS_LABEL: Record<string, string> = { DRAFT: "Draft", SIMULATED: "Simulated", REVIEWED: "Reviewed", APPROVED: "Approved", RETIRED: "Retired" };
const STATUS_CLS: Record<string, string> = { DRAFT: "bg-slate-500/20 text-slate-500", SIMULATED: "pg-adv", REVIEWED: "pg-known", APPROVED: "pg-ok", RETIRED: "bg-slate-500/20 text-slate-400" };
const SAM_LABEL: Record<string, string> = { EMPTY: "Chưa có công đoạn", COMPLETE: "Đầy đủ", INCOMPLETE: "Thiếu SAM" };

interface VersionRow {
  id: number; technology_process_id: number; layer: string; layer_label: string; version_no: number; status: string; source_type: string; source_ref: string | null;
  source_date: string | null; derived_from_version_id: number | null; total_sam_minutes: number | null; sam_status: string; expected_output_per_day: number | null;
  required_labor: number | null; note: string; editable: boolean; operation_count: number; process_code: string; style_cc: string; model_code: string; updated_at: string | null;
}
interface Operation {
  id: number; process_version_id: number; sequence_no: number; operation_code: string; operation_name: string; machine_type_code: string | null; machine_model_id: number | null;
  operator_count: number | null; helper_count: number | null; sam_minutes: number | null; cycle_time_seconds: number | null; expected_output_per_day: number | null; automation_level: string;
  setup_changeover_minutes: number | null; expected_defect_rate: number | null; source_type: string; evidence_note: string; evidence_ref: string | null; source_date: string | null;
  is_active: boolean; created_by: string; updated_by: string; change_type: string | null;
}
interface VersionDetail extends VersionRow { operations: Operation[]; assumptions_json?: Record<string, unknown> }
interface Options { layers: string[]; statuses: string[]; source_types: string[]; machine_model_statuses: string[] }
interface MachineType { code: string; name: string }
interface MachineModel { id: number; machine_type_code: string; brand: string; model: string; automation_level: string; source: string; status: string; note: string }
type Perm = { manage: boolean; review: boolean; approve: boolean; syncView: boolean; syncRun: boolean };
type Msg = { ok: boolean; text: string } | null;

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4" role="dialog" aria-modal="true" onClick={onClose}>
      <div className={`my-4 w-full ${wide ? "max-w-5xl" : "max-w-2xl"} rounded-2xl bg-white p-6 text-slate-900 shadow-xl`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between"><h3 className="text-lg font-bold">{title}</h3><button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Đóng">✕</button></div>
        {children}
      </div>
    </div>
  );
}
const F = ({ label, children }: { label: string; children: React.ReactNode }) => <label className="block text-xs text-slate-500">{label}{children}</label>;
const Notice = ({ msg }: { msg: Msg }) => (msg ? <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p> : null);

/** Quy trình công nghệ 3 tầng (Task 1 — Issue #3): Current Process / Optimized Current Technology / Future Technology.
 * SAM đi theo từng TechnologyProcessVersion (không phải master 3 tầng độc lập) — Total SAM = SUM(SAM operation active). */
export default function TechnologyProcessPanel({ perm }: { perm: Perm }) {
  const [opts, setOpts] = useState<Options>({ layers: [], statuses: [], source_types: [], machine_model_statuses: [] });
  const [machineTypes, setMachineTypes] = useState<MachineType[]>([]);
  const [rows, setRows] = useState<VersionRow[]>([]);
  const [f, setF] = useState({ style: "", model: "", layer: "", status: "", q: "" });
  const [msg, setMsg] = useState<Msg>(null);
  const [creating, setCreating] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [compareIds, setCompareIds] = useState<number[] | null>(null);
  const [machineModels, setMachineModels] = useState(false);
  const [erpSync, setErpSync] = useState(false);

  const load = useCallback(async () => {
    const params = { style: f.style || undefined, model: f.model || undefined, layer: f.layer || undefined, status: f.status || undefined, q: f.q || undefined };
    setRows((await api.get<VersionRow[]>(`${RES}/versions`, { params })).data);
  }, [f]);
  useEffect(() => {
    Promise.all([api.get<Options>(`${RES}/options`), api.get<MachineType[]>(`${RES}/machine-types`)]).then(([o, t]) => { setOpts(o.data); setMachineTypes(t.data); }).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, []);
  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })), 200);
    return () => clearTimeout(t);
  }, [load]);

  const toggleSel = (id: number) => setSelected((c) => { const n = new Set(c); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <div className="space-y-4" data-testid="tech-process-panel">
      <p className="text-xs text-slate-500">
        Quy trình công nghệ theo 3 tầng: <b>Current Process</b> (hiện tại/đã vận hành) → <b>Optimized Current Technology</b> (tối ưu bằng công nghệ/máy hiện hành — có thể mua thêm máy cùng thế hệ,
        nhưng "nhiều máy hơn" không đồng nghĩa "tốt hơn"; số lượng máy tối ưu sẽ do solver ở task sau) → <b>Future Technology</b> (công nghệ/máy mới, có thể chưa sở hữu).
        SAM là chỉ số đi theo từng phiên bản, cộng từ các công đoạn bên trong — không phải một mô hình SAM 3 tầng riêng.
      </p>
      <Notice msg={msg} />
      <div className="flex flex-wrap items-center gap-2">
        <input value={f.style} onChange={(e) => setF({ ...f, style: e.target.value })} placeholder="Style" className={`${inp} w-28`} aria-label="Style" />
        <input value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} placeholder="Model" className={`${inp} w-28`} aria-label="Model" />
        <select value={f.layer} onChange={(e) => setF({ ...f, layer: e.target.value })} className={inp} aria-label="Layer"><option value="">Mọi layer</option>{opts.layers.map((l) => <option key={l} value={l}>{LAYER_LABEL[l] ?? l}</option>)}</select>
        <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} className={inp} aria-label="Trạng thái"><option value="">Mọi trạng thái</option>{opts.statuses.map((s) => <option key={s} value={s}>{STATUS_LABEL[s] ?? s}</option>)}</select>
        <input value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} placeholder="Tìm Style/Model/mã process..." className={`${inp} w-56`} aria-label="Tìm" />
        <span className="text-xs text-slate-400">{num(rows.length)} version</span>
        <span className="flex-1" />
        {selected.size > 0 && <button onClick={() => setCompareIds([...selected])} className={btn} data-testid="compare-btn">So sánh ({selected.size})</button>}
        {perm.syncView && <button onClick={() => setErpSync(true)} className={btn} data-testid="erp-sync-open">Đồng bộ ERP QTCN</button>}
        {perm.manage && <button onClick={() => setMachineModels(true)} className={btn}>Máy (model/candidate)</button>}
        {perm.manage && <button onClick={() => setBootstrapping(true)} className={btn} data-testid="bootstrap-open">Bootstrap Current Process</button>}
        {perm.manage && <button onClick={() => setCreating(true)} className={primary} data-testid="process-add">+ Process / Version mới</button>}
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full text-sm" data-testid="version-table">
          <thead><tr><th className={th} /><th className={th}>Style</th><th className={th}>Model</th><th className={th}>Process</th><th className={th}>Layer</th><th className={`${th} text-right`}>Version</th>
            <th className={th}>Status</th><th className={`${th} text-right`}>Total SAM</th><th className={th}>Nguồn</th><th className={th}>Cập nhật</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-500/5" onClick={() => setDetailId(r.id)} data-testid={`version-row-${r.id}`}>
                <td className="px-3 py-1.5" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleSel(r.id)} aria-label={`Chọn version ${r.id} để so sánh`} /></td>
                <td className="px-3 font-mono text-xs">{r.style_cc}</td><td className="px-3">{r.model_code || "—"}</td><td className="px-3 font-mono text-xs">{r.process_code}</td>
                <td className="px-3">{r.layer_label}</td><td className="px-3 text-right">v{r.version_no}</td>
                <td className="px-3"><span className={`pg-chip ${STATUS_CLS[r.status] ?? ""}`}>{STATUS_LABEL[r.status] ?? r.status}</span></td>
                <td className="px-3 text-right">{r.sam_status === "COMPLETE" ? num(r.total_sam_minutes ?? 0) : <span className="text-amber-600" title={SAM_LABEL[r.sam_status]}>{SAM_LABEL[r.sam_status]}</span>}</td>
                <td className="px-3 text-xs text-slate-400">{r.source_type}</td><td className="px-3 text-xs text-slate-400">{r.updated_at ? dateVi(r.updated_at.slice(0, 10)) : "—"}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={10} className="py-6 text-center text-slate-400">Chưa có Technology Process nào.</td></tr>}
          </tbody>
        </table>
      </div>

      {creating && <CreateModal opts={opts} onClose={() => setCreating(false)} onDone={(id) => { setCreating(false); load(); setDetailId(id); }} setMsg={setMsg} />}
      {bootstrapping && <BootstrapModal onClose={() => setBootstrapping(false)} onDone={(id) => { setBootstrapping(false); load(); setDetailId(id); }} setMsg={setMsg} />}
      {detailId !== null && (
        <DetailModal versionId={detailId} perm={perm} opts={opts} machineTypes={machineTypes} onClose={() => setDetailId(null)} onChanged={load} setMsg={setMsg} />
      )}
      {compareIds && <CompareModal versionIds={compareIds} onClose={() => setCompareIds(null)} setMsg={setMsg} />}
      {machineModels && perm.manage && <MachineModelsModal machineTypes={machineTypes} onClose={() => setMachineModels(false)} setMsg={setMsg} />}
      {erpSync && perm.syncView && <ErpSyncModal perm={perm} onClose={() => setErpSync(false)} onApplied={load} setMsg={setMsg} />}
    </div>
  );
}

// ================================================================ Đồng bộ ERP QTCN (Task 2 — Issue #5)
const EXC_LABEL: Record<string, string> = {
  MISSING_STYLE: "Thiếu Style", AMBIGUOUS_PROCESS: "Nhiều Master trùng Style+Mùa", NO_PUBLISHED_VERSION: "Chưa có bản đã ban hành",
  INCONSISTENT_VERSION_STATUS: "Trạng thái phiên bản không nhất quán", DUPLICATE_SEQUENCE: "Trùng thứ tự công đoạn",
  MISSING_SEQUENCE: "Thiếu thứ tự công đoạn", UNMAPPED_OPERATION: "Công đoạn chưa khớp danh mục", UNMAPPED_MACHINE_TYPE: "Máy chưa khớp danh mục",
  INVALID_SOURCE_RELATION: "Quan hệ nguồn không hợp lệ", INVALID_SAM: "SAM không hợp lệ", OTHER: "Khác",
};

interface PreviewOut { source_row_count: number; out_of_scope_source_row_count: number; counts: Record<string, number>; exception_by_category: Record<string, number>; soft_exception_by_category: Record<string, number> }
interface ExceptionRow { id: number; category: string; source_key: string; reason: string; detected_at: string | null; resolution_status: string; resolution_note: string }

function ErpSyncModal({ perm, onClose, onApplied, setMsg }: { perm: Perm; onClose: () => void; onApplied: () => void; setMsg: (m: Msg) => void }) {
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [applyResult, setApplyResult] = useState<{ created: number; no_change: number; failed: number; exception_count: number; run_code: string; status: string } | null>(null);
  const [showExceptions, setShowExceptions] = useState(false);
  const [exceptions, setExceptions] = useState<ExceptionRow[]>([]);

  const runPreview = useCallback(async () => {
    setBusy(true);
    try {
      setPreview((await api.get<PreviewOut>(`${RES}/erp-sync/preview`)).data);
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(false); }
  }, [setMsg]);
  useEffect(() => { void runPreview(); }, [runPreview]);

  const runApply = async () => {
    if (!window.confirm("Chạy đồng bộ thật từ ERP QTCN? Sẽ tạo Current Process Version mới (DRAFT) cho các Style mới/thay đổi.")) return;
    setBusy(true);
    try {
      const r = await api.post<{ run_id: number; run_code: string; status: string; created: number; no_change: number; failed: number; exception_count: number }>(`${RES}/erp-sync/apply`);
      setApplyResult(r.data);
      setMsg({ ok: true, text: `Đồng bộ xong (${r.data.run_code}): tạo mới ${r.data.created}, không đổi ${r.data.no_change}, lỗi ${r.data.failed}, exception ${r.data.exception_count}.` });
      await runPreview();
      onApplied();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(false); }
  };

  const loadExceptions = async () => {
    setShowExceptions(true);
    try {
      setExceptions((await api.get<{ items: ExceptionRow[] }>(`${RES}/erp-sync/exceptions`, { params: { status: "OPEN" } })).data.items);
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };

  return (
    <Modal title="Đồng bộ Quy trình công nghệ từ ERP QTCN" onClose={onClose} wide>
      <div className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">
          Nguồn: <code>QTCN_QuyTrinhCongNghe_Master/Detail</code> (SQL Server eGMF). Chỉ tạo/import layer <b>Current Process</b>, luôn ở trạng thái DRAFT — không tự Approve.
          SAM/số lao động chưa map trong bước này (chưa xác minh được công thức ERP đáng tin) — cần bổ sung ở task sau.
        </p>
        {busy && <p className="text-xs text-slate-400">Đang tải...</p>}
        {preview && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-slate-200 p-3"><div className="text-[11px] uppercase text-slate-400">Style mới</div><div className="text-xl font-bold text-green-600">{preview.counts.NEW ?? 0}</div></div>
            <div className="rounded-xl border border-slate-200 p-3"><div className="text-[11px] uppercase text-slate-400">Đã thay đổi</div><div className="text-xl font-bold text-amber-600">{preview.counts.CHANGED ?? 0}</div></div>
            <div className="rounded-xl border border-slate-200 p-3"><div className="text-[11px] uppercase text-slate-400">Không đổi</div><div className="text-xl font-bold text-slate-500">{preview.counts.NO_CHANGE ?? 0}</div></div>
            <div className="rounded-xl border border-slate-200 p-3"><div className="text-[11px] uppercase text-slate-400">Exception</div><div className="text-xl font-bold text-red-600">{preview.counts.EXCEPTION ?? 0}</div></div>
          </div>
        )}
        {preview && Object.keys(preview.exception_by_category).length > 0 && (
          <div className="text-xs text-slate-500">
            {Object.entries(preview.exception_by_category).map(([k, v]) => <span key={k} className="mr-3">{EXC_LABEL[k] ?? k}: <b>{v}</b></span>)}
          </div>
        )}
        {preview && preview.out_of_scope_source_row_count > 0 && (
          <p className="text-xs text-slate-400">{num(preview.out_of_scope_source_row_count)} dòng nguồn ngoài phạm vi (thư viện công đoạn dùng chung, IdQTCN=-1) — không tính vào exception.</p>
        )}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button onClick={() => void runPreview()} className={btn} disabled={busy}>↻ Preview lại</button>
          {perm.syncRun && <button onClick={() => void runApply()} className={primary} disabled={busy}>Apply Sync</button>}
          <button onClick={() => void loadExceptions()} className={btn}>Xem exception</button>
        </div>
        {applyResult && (
          <p className="text-xs text-slate-500">Lần chạy gần nhất <b>{applyResult.run_code}</b> ({applyResult.status}): tạo mới {applyResult.created}, không đổi {applyResult.no_change}, lỗi {applyResult.failed}, exception {applyResult.exception_count}.</p>
        )}
        {showExceptions && (
          <div className="max-h-64 overflow-y-auto rounded-xl border border-slate-200">
            <table className="w-full text-xs">
              <thead><tr><th className={th}>Loại</th><th className={th}>Source key</th><th className={th}>Lý do</th></tr></thead>
              <tbody>
                {exceptions.map((e) => (
                  <tr key={e.id} className="border-t border-slate-100"><td className="px-3 py-1.5">{EXC_LABEL[e.category] ?? e.category}</td><td className="px-3 font-mono">{e.source_key}</td><td className="px-3 text-slate-500">{e.reason}</td></tr>
                ))}
                {exceptions.length === 0 && <tr><td colSpan={3} className="py-4 text-center text-slate-400">Không có exception đang mở.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}

// ================================================================ Tạo Process + Version đầu tiên
function CreateModal({ opts, onClose, onDone, setMsg }: { opts: Options; onClose: () => void; onDone: (versionId: number) => void; setMsg: (m: Msg) => void }) {
  const [d, setD] = useState({ style_cc: "", model_code: "", product_family: "", description: "", layer: "CURRENT_PROCESS", source_type: "MANUAL", source_ref: "", note: "" });
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const p = (await api.post(`${RES}/processes`, { style_cc: d.style_cc, model_code: d.model_code || undefined, product_family: d.product_family || undefined, description: d.description || undefined })).data;
      const v = (await api.post(`${RES}/processes/${p.id}/versions`, { layer: d.layer, source_type: d.source_type, source_ref: d.source_ref || undefined, note: d.note || undefined })).data;
      onDone(v.id);
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(false); }
  };
  return (
    <Modal title="Process / Version mới" onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <F label="Style/CC"><input className={inp} value={d.style_cc} onChange={(e) => setD({ ...d, style_cc: e.target.value })} data-testid="new-style" /></F>
        <F label="Model (không bắt buộc)"><input className={inp} value={d.model_code} onChange={(e) => setD({ ...d, model_code: e.target.value })} /></F>
        <F label="Product family"><input className={inp} value={d.product_family} onChange={(e) => setD({ ...d, product_family: e.target.value })} /></F>
        <F label="Mô tả"><input className={inp} value={d.description} onChange={(e) => setD({ ...d, description: e.target.value })} /></F>
        <F label="Layer"><select className={inp} value={d.layer} onChange={(e) => setD({ ...d, layer: e.target.value })}>{opts.layers.map((l) => <option key={l} value={l}>{LAYER_LABEL[l] ?? l}</option>)}</select></F>
        <F label="Nguồn (source_type)"><select className={inp} value={d.source_type} onChange={(e) => setD({ ...d, source_type: e.target.value })}>{opts.source_types.map((s) => <option key={s} value={s}>{s}</option>)}</select></F>
        <div className="col-span-2"><F label="source_ref (bằng chứng nguồn)"><input className={inp} value={d.source_ref} onChange={(e) => setD({ ...d, source_ref: e.target.value })} placeholder="VD: QTCN routing #123, IE standard 2026-09..." /></F></div>
        <div className="col-span-2"><F label="Ghi chú"><input className={inp} value={d.note} onChange={(e) => setD({ ...d, note: e.target.value })} /></F></div>
      </div>
      <p className="mt-3 text-[11px] text-slate-400">Version tạo ở trạng thái <b>Draft</b>. Nếu Style/Model đã có Process, hệ thống sẽ báo lỗi — hãy mở Process đó và thêm version layer mới từ màn danh sách.</p>
      <div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
        <button onClick={submit} disabled={busy || !d.style_cc.trim()} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="create-submit">Tạo</button></div>
    </Modal>
  );
}

// ================================================================ Bootstrap Current Process (§11) — thủ công/normalized, KHÔNG nối live ERP
function BootstrapModal({ onClose, onDone, setMsg }: { onClose: () => void; onDone: (versionId: number) => void; setMsg: (m: Msg) => void }) {
  const [d, setD] = useState({ style_cc: "", model_code: "", source_ref: "", note: "" });
  const [ops, setOps] = useState([{ operation_name: "", sam_minutes: "", operator_count: "1", evidence_note: "" }]);
  const [busy, setBusy] = useState(false);
  const patch = (i: number, p: Partial<(typeof ops)[number]>) => setOps((c) => c.map((o, k) => (k === i ? { ...o, ...p } : o)));
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post(`${RES}/bootstrap`, {
        style_cc: d.style_cc, model_code: d.model_code || undefined, source_ref: d.source_ref, note: d.note || undefined,
        operations: ops.filter((o) => o.operation_name.trim()).map((o) => ({ operation_name: o.operation_name, sam_minutes: o.sam_minutes ? Number(o.sam_minutes) : undefined, operator_count: Number(o.operator_count || 0), evidence_note: o.evidence_note || undefined })),
      });
      setMsg({ ok: true, text: r.data.created ? "Đã bootstrap Current Process (version mới)." : "Đã có version với cùng nội dung — không tạo trùng (idempotent)." });
      onDone(r.data.version.id);
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(false); }
  };
  return (
    <Modal title="Bootstrap Current Process (thủ công)" onClose={onClose} wide>
      <p className="text-xs text-amber-700">Chưa nối live ERP QTCN (Known Gap của Task 1). Nhập dữ liệu đã chuẩn hóa thủ công; chạy lại với cùng nội dung sẽ không tạo bản trùng.</p>
      <div className="mt-3 grid grid-cols-3 gap-3">
        <F label="Style/CC"><input className={inp} value={d.style_cc} onChange={(e) => setD({ ...d, style_cc: e.target.value })} data-testid="bs-style" /></F>
        <F label="Model"><input className={inp} value={d.model_code} onChange={(e) => setD({ ...d, model_code: e.target.value })} /></F>
        <F label="source_ref (bắt buộc)"><input className={inp} value={d.source_ref} onChange={(e) => setD({ ...d, source_ref: e.target.value })} placeholder="VD: QTCN export 2026-09-22" data-testid="bs-ref" /></F>
      </div>
      <table className="mt-3 w-full text-sm">
        <thead><tr className="text-[11px] uppercase text-slate-400"><th className="text-left">Công đoạn</th><th className="text-right">SAM</th><th className="text-right">Operator</th><th className="text-left">Evidence</th><th /></tr></thead>
        <tbody>
          {ops.map((o, i) => (
            <tr key={i}>
              <td className="py-1 pr-1"><input className={inp} value={o.operation_name} onChange={(e) => patch(i, { operation_name: e.target.value })} /></td>
              <td className="py-1 pr-1"><input type="number" step="0.01" className={`${inp} text-right`} value={o.sam_minutes} onChange={(e) => patch(i, { sam_minutes: e.target.value })} /></td>
              <td className="py-1 pr-1"><input type="number" className={`${inp} text-right`} value={o.operator_count} onChange={(e) => patch(i, { operator_count: e.target.value })} /></td>
              <td className="py-1 pr-1"><input className={inp} value={o.evidence_note} onChange={(e) => patch(i, { evidence_note: e.target.value })} /></td>
              <td><button onClick={() => setOps((c) => c.filter((_o, k) => k !== i))} disabled={ops.length <= 1} className="text-slate-400 disabled:opacity-30">✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={() => setOps((c) => [...c, { operation_name: "", sam_minutes: "", operator_count: "1", evidence_note: "" }])} className={`${btn} mt-2`}>+ Công đoạn</button>
      <div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
        <button onClick={submit} disabled={busy || !d.style_cc.trim() || !d.source_ref.trim() || !ops.some((o) => o.operation_name.trim())} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="bs-submit">Bootstrap</button></div>
    </Modal>
  );
}

// ================================================================ Detail (process/version/operations)
function DetailModal({ versionId, perm, opts, machineTypes, onClose, onChanged, setMsg }: { versionId: number; perm: Perm; opts: Options; machineTypes: MachineType[]; onClose: () => void; onChanged: () => void; setMsg: (m: Msg) => void }) {
  const [v, setV] = useState<VersionDetail | null>(null);
  const [machineModels, setMachineModels] = useState<MachineModel[]>([]);
  const [editOp, setEditOp] = useState<Partial<Operation> & { isNew?: boolean } | null>(null);
  const [deriving, setDeriving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const [comparing, setComparing] = useState(false);

  const load = useCallback(async () => {
    const [vd, mm] = await Promise.all([api.get<VersionDetail>(`${RES}/versions/${versionId}`), api.get<MachineModel[]>(`${RES}/machine-models`)]);
    setV(vd.data); setMachineModels(mm.data);
  }, [versionId]);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); await load(); onChanged(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const saveOp = async () => {
    if (!editOp) return;
    // operator_count: giữ nguyên null nếu đang null ("Chưa xác định" — VD operation nhập từ ERP) thay vì ép về 0,
    // 0 và "chưa biết" có nghĩa nghiệp vụ khác nhau (Task 2, Issue #5 PR #6 review mục 4).
    const body = { ...editOp, sequence_no: editOp.sequence_no ? Number(editOp.sequence_no) : undefined, operator_count: editOp.operator_count === null || editOp.operator_count === undefined ? null : Number(editOp.operator_count),
      helper_count: editOp.helper_count ?? undefined, sam_minutes: editOp.sam_minutes ?? undefined, machine_type_code: editOp.machine_type_code || undefined, machine_model_id: editOp.machine_model_id || undefined };
    const ok = await (async () => {
      try {
        if (editOp.isNew) await api.post(`${RES}/versions/${versionId}/operations`, body);
        else await api.put(`${RES}/operations/${editOp.id}`, body);
        return true;
      } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); return false; }
    })();
    if (ok) { setEditOp(null); await load(); onChanged(); }
  };
  const removeOp = (op: Operation) => {
    const reason = window.prompt("Lý do gỡ công đoạn này?") ?? "";
    if (!reason.trim()) return;
    void act(() => api.post(`${RES}/operations/${op.id}/remove`, { reason }), "Đã gỡ công đoạn.");
  };

  if (!v) return <Modal title="Đang tải..." onClose={onClose}><p className="text-sm text-slate-400">Đang tải...</p></Modal>;
  const modelsFor = (type: string | null | undefined) => machineModels.filter((m) => !type || m.machine_type_code === type);

  return (
    <Modal title={`${v.style_cc} / ${v.model_code || "—"} · ${v.layer_label} v${v.version_no}`} onClose={onClose} wide>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={`pg-chip ${STATUS_CLS[v.status] ?? ""}`}>{STATUS_LABEL[v.status] ?? v.status}</span>
        <span className="text-slate-400">{v.process_code} · nguồn {v.source_type}{v.source_ref ? ` (${v.source_ref})` : ""}</span>
        {v.derived_from_version_id && <span className="text-slate-400">· derived từ version #{v.derived_from_version_id}</span>}
        <span className="flex-1" />
        <span className="font-semibold">Total SAM: {v.sam_status === "COMPLETE" ? num(v.total_sam_minutes ?? 0) : <span className="text-amber-600">{SAM_LABEL[v.sam_status]}</span>}</span>
      </div>

      {perm.manage && v.editable && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button onClick={() => setEditOp({ isNew: true, operator_count: 0 })} className={btn} data-testid="op-add">+ Công đoạn</button>
          <button onClick={() => act(() => api.post(`${RES}/versions/${versionId}/recalc-sam`), "Đã tính lại Total SAM.")} className={btn}>Tính lại SAM</button>
          {v.status === "DRAFT" && <button onClick={() => act(() => api.post(`${RES}/versions/${versionId}/simulate`), "Đã chuyển Simulated.")} className={btn}>→ Simulated</button>}
          <button onClick={() => setDeriving(true)} className={btn} data-testid="derive-open">Derive sang layer khác</button>
          {v.layer === "CURRENT_PROCESS" && <button onClick={() => setGenerating(true)} className={btn} data-testid="generate-optimized-open">Tạo đề xuất Optimized Current Technology</button>}
        </div>
      )}
      {v.source_type === "AUTO_GENERATED" && (
        <div className="mt-2 flex flex-wrap gap-2">
          <button onClick={() => setShowEvidence(true)} className={btn}>Generation Evidence</button>
          {v.derived_from_version_id && <button onClick={() => setComparing(true)} className={btn}>So sánh với Current gốc</button>}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {perm.review && (v.status === "DRAFT" || v.status === "SIMULATED") && <button onClick={() => act(() => api.post(`${RES}/versions/${versionId}/review`), "Đã chuyển Reviewed.")} className={btn}>→ Review</button>}
        {perm.approve && v.status === "REVIEWED" && <button onClick={() => act(() => api.post(`${RES}/versions/${versionId}/approve`), "Đã Approve — nội dung kỹ thuật từ nay bất biến.")} className={primary}>→ Approve</button>}
        {perm.approve && v.status === "APPROVED" && <button onClick={() => { if (window.confirm("Retire version này?")) void act(() => api.post(`${RES}/versions/${versionId}/retire`), "Đã Retire."); }} className="rounded-full border border-red-400/60 px-3 py-1.5 text-xs text-red-600">Retire</button>}
      </div>
      {!v.editable && <p className="mt-2 text-[11px] text-amber-700">Version {v.status} — nội dung kỹ thuật bất biến. Muốn thay đổi, hãy Derive sang version mới.</p>}

      <table className="mt-4 w-full text-sm">
        <thead><tr className="text-[11px] uppercase text-slate-400"><th className="text-left">#</th><th className="text-left">Công đoạn</th><th className="text-left">Máy</th><th className="text-right">Operator</th><th className="text-right">Helper</th><th className="text-right">SAM</th><th className="text-left">Thay đổi</th><th className="text-left">Nguồn/Evidence</th>{perm.manage && v.editable && <th />}</tr></thead>
        <tbody>
          {v.operations.filter((o) => o.is_active).map((o) => (
            <tr key={o.id} className="border-t border-slate-100">
              <td className="py-1">{o.sequence_no}</td><td>{o.operation_name}</td>
              <td className="text-xs">{o.machine_type_code ?? "—"}{o.machine_model_id ? ` · ${machineModels.find((m) => m.id === o.machine_model_id)?.model ?? "#" + o.machine_model_id}` : ""}</td>
              <td className="text-right">{o.operator_count ?? <span className="text-slate-400" title="Chưa xác định">—</span>}</td><td className="text-right">{o.helper_count ?? "—"}</td>
              <td className="text-right">{o.sam_minutes ?? <span className="text-amber-600">thiếu</span>}</td>
              <td className="text-xs">{o.change_type && o.change_type !== "UNCHANGED" ? <span className="pg-chip pg-adv">{o.change_type}</span> : (o.change_type ? <span className="text-slate-400">Giữ nguyên</span> : "—")}</td>
              <td className="max-w-[200px] truncate text-xs text-slate-400" title={o.evidence_note}>{o.source_type}{o.evidence_note ? ` · ${o.evidence_note}` : ""}</td>
              {perm.manage && v.editable && <td className="whitespace-nowrap text-right text-xs"><button onClick={() => setEditOp(o)} className="text-brand hover:underline">Sửa</button><button onClick={() => removeOp(o)} className="ml-2 text-red-500 hover:underline">Gỡ</button></td>}
            </tr>
          ))}
          {v.operations.filter((o) => o.is_active).length === 0 && <tr><td colSpan={9} className="py-4 text-center text-slate-400">Chưa có công đoạn nào.</td></tr>}
        </tbody>
      </table>

      {editOp && (
        <Modal title={editOp.isNew ? "Thêm công đoạn" : `Sửa công đoạn #${editOp.sequence_no}`} onClose={() => setEditOp(null)}>
          <div className="grid grid-cols-2 gap-3">
            <F label="Thứ tự"><input type="number" className={inp} value={editOp.sequence_no ?? ""} onChange={(e) => setEditOp({ ...editOp, sequence_no: Number(e.target.value) })} /></F>
            <F label="Tên công đoạn"><input className={inp} value={editOp.operation_name ?? ""} onChange={(e) => setEditOp({ ...editOp, operation_name: e.target.value })} /></F>
            <F label="Loại máy"><select className={inp} value={editOp.machine_type_code ?? ""} onChange={(e) => setEditOp({ ...editOp, machine_type_code: e.target.value || null, machine_model_id: null })}><option value="">—</option>{machineTypes.map((t) => <option key={t.code} value={t.code}>{t.code} · {t.name}</option>)}</select></F>
            <F label="Model/Candidate"><select className={inp} value={editOp.machine_model_id ?? ""} onChange={(e) => setEditOp({ ...editOp, machine_model_id: e.target.value ? Number(e.target.value) : null })}><option value="">—</option>{modelsFor(editOp.machine_type_code).map((m) => <option key={m.id} value={m.id}>{m.brand} {m.model} ({m.status})</option>)}</select></F>
            <F label="Operator (để trống = chưa xác định)"><input type="number" className={inp} value={editOp.operator_count ?? ""} onChange={(e) => setEditOp({ ...editOp, operator_count: e.target.value === "" ? null : Number(e.target.value) })} /></F>
            <F label="Helper"><input type="number" className={inp} value={editOp.helper_count ?? ""} onChange={(e) => setEditOp({ ...editOp, helper_count: e.target.value === "" ? null : Number(e.target.value) })} /></F>
            <F label="SAM (phút)"><input type="number" step="0.01" className={inp} value={editOp.sam_minutes ?? ""} onChange={(e) => setEditOp({ ...editOp, sam_minutes: e.target.value === "" ? null : Number(e.target.value) })} /></F>
            <F label="Cycle time (giây)"><input type="number" step="0.1" className={inp} value={editOp.cycle_time_seconds ?? ""} onChange={(e) => setEditOp({ ...editOp, cycle_time_seconds: e.target.value === "" ? null : Number(e.target.value) })} /></F>
            <F label="Nguồn (source_type)"><select className={inp} value={editOp.source_type ?? "MANUAL"} onChange={(e) => setEditOp({ ...editOp, source_type: e.target.value })}>{opts.source_types.map((s) => <option key={s} value={s}>{s}</option>)}</select></F>
            <F label="Evidence ref"><input className={inp} value={editOp.evidence_ref ?? ""} onChange={(e) => setEditOp({ ...editOp, evidence_ref: e.target.value })} /></F>
            <div className="col-span-2"><F label="Evidence note"><input className={inp} value={editOp.evidence_note ?? ""} onChange={(e) => setEditOp({ ...editOp, evidence_note: e.target.value })} /></F></div>
          </div>
          <div className="mt-5 flex justify-end gap-2"><button onClick={() => setEditOp(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={saveOp} disabled={!editOp.operation_name?.trim()} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="op-save">Lưu</button></div>
        </Modal>
      )}
      {deriving && (
        <DeriveModal opts={opts} onClose={() => setDeriving(false)} onDone={(id) => { setDeriving(false); onChanged(); setMsg({ ok: true, text: "Đã tạo version mới (derive)." }); window.setTimeout(() => { onClose(); }, 0); void id; }} versionId={versionId} setMsg={setMsg} />
      )}
      {generating && (
        <GenerateOptimizedModal versionId={versionId} onClose={() => setGenerating(false)} onDone={() => { setGenerating(false); onChanged(); setMsg({ ok: true, text: "Đã tạo đề xuất Optimized Current Technology." }); window.setTimeout(() => { onClose(); }, 0); }} setMsg={setMsg} />
      )}
      {showEvidence && <GenerationEvidenceModal assumptions={v.assumptions_json ?? {}} onClose={() => setShowEvidence(false)} />}
      {comparing && v.derived_from_version_id && <CompareCurrentOptimizedModal optimizedId={v.id} onClose={() => setComparing(false)} setMsg={setMsg} />}
    </Modal>
  );
}

// ================================================================ Task 3 — Optimized Current Technology Generator (Issue #7)
interface PreviewCandidate { id: number; candidate_machine_type_code: string; candidate_machine_model_id: number | null; machine_model_status: string | null; compatibility_status: string; eligible: boolean }
interface PreviewOp { sequence_no: number; operation_code: string; operation_name: string; current_machine_type_code: string | null; decision: string; auto_candidate_id: number | null; candidates: PreviewCandidate[] }
const DECISION_LABEL: Record<string, string> = { UNCHANGED: "Giữ nguyên", MACHINE_SUBSTITUTION: "Đề xuất thay máy (tự động)", MULTIPLE_CANDIDATES: "Nhiều lựa chọn — cần chọn tay", UNVERIFIED_CANDIDATE_AVAILABLE: "Có lựa chọn chưa kiểm chứng" };

function GenerateOptimizedModal({ versionId, onClose, onDone, setMsg }: { versionId: number; onClose: () => void; onDone: (id: number) => void; setMsg: (m: Msg) => void }) {
  const [ops, setOps] = useState<PreviewOp[] | null>(null);
  const [selections, setSelections] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<{ operations: PreviewOp[] }>(`${RES}/versions/${versionId}/optimized-preview`).then((r) => setOps(r.data.operations)).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, [versionId, setMsg]);

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ created: boolean; version: { id: number } }>(`${RES}/versions/${versionId}/generate-optimized`, { selections });
      if (!r.data.created) setMsg({ ok: true, text: "Không có gì thay đổi so với đề xuất đã có — dùng lại proposal cũ." });
      onDone(r.data.version.id);
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(false); }
  };

  return (
    <Modal title="Tạo đề xuất Optimized Current Technology" onClose={onClose} wide>
      <p className="text-xs text-slate-500">
        Copy toàn bộ công đoạn từ Current Process; chỉ thay máy ở công đoạn có candidate đủ điều kiện (compatibility đã Approved và máy/model đã Approved hoặc Trial).
        Không tự bịa SAM/output/lao động — giữ nguyên giá trị hiện có (thường chưa có). Với công đoạn có nhiều lựa chọn hoặc lựa chọn chưa kiểm chứng, hãy chọn tay bên dưới.
      </p>
      {!ops && <p className="mt-3 text-xs text-slate-400">Đang tải...</p>}
      {ops && (
        <div className="mt-3 max-h-96 overflow-y-auto rounded-xl border border-slate-200">
          <table className="w-full text-xs">
            <thead><tr className="text-[11px] uppercase text-slate-400"><th className={th}>#</th><th className={th}>Công đoạn</th><th className={th}>Máy hiện tại</th><th className={th}>Quyết định</th><th className={th}>Chọn candidate</th></tr></thead>
            <tbody>
              {ops.map((o) => (
                <tr key={o.sequence_no} className="border-t border-slate-100">
                  <td className="px-3 py-1.5">{o.sequence_no}</td><td className="px-3">{o.operation_name}</td><td className="px-3">{o.current_machine_type_code ?? "—"}</td>
                  <td className="px-3">{DECISION_LABEL[o.decision] ?? o.decision}</td>
                  <td className="px-3">
                    {(o.decision === "MULTIPLE_CANDIDATES" || o.decision === "UNVERIFIED_CANDIDATE_AVAILABLE") && o.candidates.length > 0 ? (
                      <select className={inp} value={selections[String(o.sequence_no)] ?? ""} onChange={(e) => setSelections((s) => ({ ...s, [String(o.sequence_no)]: Number(e.target.value) }))}>
                        <option value="">Giữ nguyên</option>
                        {o.candidates.map((c) => <option key={c.id} value={c.id}>{c.candidate_machine_type_code} ({c.compatibility_status}{c.machine_model_status ? `/model ${c.machine_model_status}` : ""}){c.eligible ? "" : " — chưa kiểm chứng"}</option>)}
                      </select>
                    ) : (o.auto_candidate_id ? "Tự động" : "—")}
                  </td>
                </tr>
              ))}
              {ops.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-slate-400">Version nguồn chưa có công đoạn nào.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
        <button onClick={submit} disabled={busy || !ops} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="generate-optimized-submit">Generate</button></div>
    </Modal>
  );
}

function GenerationEvidenceModal({ assumptions, onClose }: { assumptions: Record<string, unknown>; onClose: () => void }) {
  return (
    <Modal title="Generation Evidence" onClose={onClose} wide>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(assumptions, null, 2)}</pre>
    </Modal>
  );
}

function CompareCurrentOptimizedModal({ optimizedId, onClose, setMsg }: { optimizedId: number; onClose: () => void; setMsg: (m: Msg) => void }) {
  interface CompareOut {
    operation_changed_count: number; machine_substitution_count: number; automation_change_count: number;
    total_sam_minutes: { a: number | null; b: number | null }; sam_status: { a: string; b: string };
    required_labor: { a: number | null; b: number | null }; expected_output_per_day: { a: number | null; b: number | null };
  }
  const [c, setC] = useState<CompareOut | null>(null);
  useEffect(() => {
    api.get<CompareOut>(`${RES}/versions/${optimizedId}/compare-with-source`).then((r) => setC(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, [optimizedId, setMsg]);
  const naOr = (v: number | null) => (v === null ? <span className="text-slate-400">N/A</span> : num(v));
  return (
    <Modal title="So sánh Current Process vs Optimized Current Technology" onClose={onClose}>
      {!c && <p className="text-xs text-slate-400">Đang tải...</p>}
      {c && (
        <div className="space-y-2 text-sm">
          <p>Số công đoạn thay đổi: <b>{c.operation_changed_count}</b></p>
          <p>Thay máy (machine substitution): <b>{c.machine_substitution_count}</b></p>
          <p>Nâng cấp tự động hóa: <b>{c.automation_change_count}</b></p>
          <p>Total SAM: {naOr(c.total_sam_minutes.a)} → {naOr(c.total_sam_minutes.b)} ({c.sam_status.a} → {c.sam_status.b})</p>
          <p>Required labor: {naOr(c.required_labor.a)} → {naOr(c.required_labor.b)}</p>
          <p>Expected output/day: {naOr(c.expected_output_per_day.a)} → {naOr(c.expected_output_per_day.b)}</p>
        </div>
      )}
    </Modal>
  );
}

function DeriveModal({ versionId, opts, onClose, onDone, setMsg }: { versionId: number; opts: Options; onClose: () => void; onDone: (id: number) => void; setMsg: (m: Msg) => void }) {
  const [layer, setLayer] = useState(opts.layers[1] ?? "OPTIMIZED_CURRENT_TECHNOLOGY");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post(`${RES}/versions/${versionId}/derive`, { target_layer: layer, note: note || undefined });
      onDone(r.data.id);
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(false); }
  };
  return (
    <Modal title="Derive sang layer khác" onClose={onClose}>
      <p className="text-xs text-slate-500">Tạo version Draft mới, copy các công đoạn đang active của version hiện tại. Không tự đồng bộ về sau — sửa version nguồn sẽ không ảnh hưởng bản derive này.</p>
      <div className="mt-3 grid grid-cols-1 gap-3">
        <F label="Layer đích"><select className={inp} value={layer} onChange={(e) => setLayer(e.target.value)}>{opts.layers.map((l) => <option key={l} value={l}>{LAYER_LABEL[l] ?? l}</option>)}</select></F>
        <F label="Ghi chú"><input className={inp} value={note} onChange={(e) => setNote(e.target.value)} /></F>
      </div>
      <div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
        <button onClick={submit} disabled={busy} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="derive-submit">Tạo</button></div>
    </Modal>
  );
}

// ================================================================ Compare (§13)
function CompareModal({ versionIds, onClose, setMsg }: { versionIds: number[]; onClose: () => void; setMsg: (m: Msg) => void }) {
  const [rows, setRows] = useState<(VersionRow & { operation_count: number; machine_summary: { machine_type_code: string; machine_model_id: number | null }[] })[]>([]);
  useEffect(() => {
    api.get(`${RES}/versions/compare`, { params: { version_ids: versionIds.join(",") } }).then((r) => setRows(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, [versionIds, setMsg]);
  return (
    <Modal title="So sánh version" onClose={onClose} wide>
      <table className="w-full text-sm">
        <thead><tr><th className={th}>Chỉ tiêu</th>{rows.map((r) => <th key={r.id} className={th}>{r.style_cc}/{r.model_code || "—"} · {r.layer_label} v{r.version_no}</th>)}</tr></thead>
        <tbody>
          <tr className="border-t border-slate-100"><td className="px-3 py-1.5 font-semibold">Trạng thái</td>{rows.map((r) => <td key={r.id} className="px-3"><span className={`pg-chip ${STATUS_CLS[r.status] ?? ""}`}>{STATUS_LABEL[r.status] ?? r.status}</span></td>)}</tr>
          <tr className="border-t border-slate-100"><td className="px-3 py-1.5 font-semibold">Total SAM</td>{rows.map((r) => <td key={r.id} className="px-3">{r.sam_status === "COMPLETE" ? num(r.total_sam_minutes ?? 0) : SAM_LABEL[r.sam_status]}</td>)}</tr>
          <tr className="border-t border-slate-100"><td className="px-3 py-1.5 font-semibold">Số công đoạn</td>{rows.map((r) => <td key={r.id} className="px-3">{r.operation_count}</td>)}</tr>
          <tr className="border-t border-slate-100"><td className="px-3 py-1.5 font-semibold">Required labor</td>{rows.map((r) => <td key={r.id} className="px-3">{r.required_labor ?? "—"}</td>)}</tr>
          <tr className="border-t border-slate-100"><td className="px-3 py-1.5 font-semibold">Expected output/ngày</td>{rows.map((r) => <td key={r.id} className="px-3">{r.expected_output_per_day ?? "—"}</td>)}</tr>
          <tr className="border-t border-slate-100"><td className="px-3 py-1.5 align-top font-semibold">Máy sử dụng</td>{rows.map((r) => <td key={r.id} className="px-3 text-xs">{r.machine_summary.length ? r.machine_summary.map((m, i) => <div key={i}>{m.machine_type_code || "—"}{m.machine_model_id ? ` · #${m.machine_model_id}` : ""}</div>) : "—"}</td>)}</tr>
        </tbody>
      </table>
    </Modal>
  );
}

// ================================================================ Machine Model / Candidate (§10)
function MachineModelsModal({ machineTypes, onClose, setMsg }: { machineTypes: MachineType[]; onClose: () => void; setMsg: (m: Msg) => void }) {
  const [rows, setRows] = useState<MachineModel[]>([]);
  const [edit, setEdit] = useState<Partial<MachineModel> & { isNew?: boolean } | null>(null);
  const load = useCallback(async () => setRows((await api.get<MachineModel[]>(`${RES}/machine-models`)).data), []);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const save = async () => {
    if (!edit) return;
    try {
      if (edit.isNew) await api.post(`${RES}/machine-models`, edit);
      else await api.put(`${RES}/machine-models/${edit.id}`, edit);
      setEdit(null);
      await load();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  return (
    <Modal title="Máy — Model / Candidate" onClose={onClose} wide>
      <p className="text-xs text-slate-500">Danh mục dùng chung, không thuộc riêng một Technology Process nào — nhiều Operation của nhiều Style có thể cùng tham chiếu một model. Trạng thái CANDIDATE/TRIAL/APPROVED/REJECTED — không tự động Approved.</p>
      <div className="mt-2"><button onClick={() => setEdit({ isNew: true, status: "CANDIDATE" })} className={primary} data-testid="mm-add">+ Model mới</button></div>
      <table className="mt-3 w-full text-sm">
        <thead><tr className="text-[11px] uppercase text-slate-400"><th className="text-left">Loại máy</th><th className="text-left">Brand/Model</th><th className="text-left">Automation</th><th className="text-left">Trạng thái</th><th /></tr></thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.id} className="border-t border-slate-100">
              <td className="py-1">{m.machine_type_code}</td><td>{m.brand} {m.model}</td><td>{m.automation_level || "—"}</td>
              <td><span className={`pg-chip ${m.status === "APPROVED" ? "pg-ok" : m.status === "REJECTED" ? "pg-late" : "bg-slate-500/20 text-slate-500"}`}>{m.status}</span></td>
              <td className="text-right text-xs"><button onClick={() => setEdit(m)} className="text-brand hover:underline">Sửa</button></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-slate-400">Chưa có model nào.</td></tr>}
        </tbody>
      </table>
      {edit && (
        <Modal title={edit.isNew ? "Thêm Machine Model" : "Sửa Machine Model"} onClose={() => setEdit(null)}>
          <div className="grid grid-cols-2 gap-3">
            <F label="Loại máy"><select className={inp} value={edit.machine_type_code ?? ""} onChange={(e) => setEdit({ ...edit, machine_type_code: e.target.value })}><option value="">—</option>{machineTypes.map((t) => <option key={t.code} value={t.code}>{t.code} · {t.name}</option>)}</select></F>
            <F label="Trạng thái"><select className={inp} value={edit.status ?? "CANDIDATE"} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>{["CANDIDATE", "TRIAL", "APPROVED", "REJECTED"].map((s) => <option key={s} value={s}>{s}</option>)}</select></F>
            <F label="Brand"><input className={inp} value={edit.brand ?? ""} onChange={(e) => setEdit({ ...edit, brand: e.target.value })} /></F>
            <F label="Model"><input className={inp} value={edit.model ?? ""} onChange={(e) => setEdit({ ...edit, model: e.target.value })} /></F>
            <F label="Automation level"><input className={inp} value={edit.automation_level ?? ""} onChange={(e) => setEdit({ ...edit, automation_level: e.target.value })} /></F>
            <F label="Nguồn thông tin"><input className={inp} value={edit.source ?? ""} onChange={(e) => setEdit({ ...edit, source: e.target.value })} placeholder="brochure, trial, nhập tay..." /></F>
            <div className="col-span-2"><F label="Ghi chú"><input className={inp} value={edit.note ?? ""} onChange={(e) => setEdit({ ...edit, note: e.target.value })} /></F></div>
          </div>
          <div className="mt-5 flex justify-end gap-2"><button onClick={() => setEdit(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={save} disabled={!edit.machine_type_code} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="mm-save">Lưu</button></div>
        </Modal>
      )}
    </Modal>
  );
}
