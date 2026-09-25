import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { dateVi, num } from "../../lib/format";

const RES = "/roadmap";
const inp = "w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400 whitespace-nowrap";
const btn = "rounded-full border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40";
const primary = "rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-40";

type Msg = { ok: boolean; text: string } | null;
interface Options {
  lifecycle_statuses: string[]; scope_types: string[]; metric_codes: string[]; target_kinds: string[]; period_types: string[];
  baseline_bases: Record<string, string[]>; canonical_units: Record<string, string>; proposal_types: string[]; rule_proposal_types: string[];
}
interface Scenario { id: number; scenario_code: string; name: string; description: string; scope_type: string; scope_value: string; owner: string; status: string; allowed_transitions: string[]; versions?: { id: number; version_no: number; status: string; note: string }[] }
interface Target {
  id: number; metric_code: string; target_kind: string; target_value: number; unit: string; scope_type: string; scope_value: string; period_type: string; period_year: number;
  period_month: number | null; baseline_basis: string | null; baseline_ref_year: number | null; baseline_ref_month: number | null; note: string;
}
interface Milestone { id: number; code: string; name: string; target_date: string; sequence: number; note: string; targets: Target[] }
interface Version {
  id: number; scenario_id: number; version_no: number; status: string; scope_type: string; scope_value: string; note: string; editable: boolean; allowed_transitions: string[];
  locked_at: string | null; copied_from_version_id: number | null; milestones: Milestone[]; technology_links: { id: number; link_type: string; ref_id: number; note: string }[];
}
interface RunRow { id: number; run_no: number; created_by: string; created_at: string; summary: { completeness: string; target_result_counts: Record<string, number>; proposal_status_counts: Record<string, number>; data_quality_flags: string[] } }
interface Result {
  id: number; milestone_code: string; metric_code: string; target_kind: string; target_value: number; increment_value: number | null; effective_target: number | null; unit: string;
  period_label: string; baseline_basis: string | null; baseline_period_label: string; output_definition: string | null; baseline_value: number | null; baseline_unit: string; gap: number | null;
  result_status: string; source_identity: Record<string, unknown>; source_meta: Record<string, unknown>; data_quality_flags: string[]; missing_inputs: string[]; completeness: string;
}
interface Proposal {
  id: number; milestone_code: string; proposal_type: string; quantity: number | null; unit: string; rationale: string; calculation_rule_version: string; input_snapshot: Record<string, unknown>;
  evidence_refs: unknown[]; missing_inputs: string[]; completeness: string; calc_status: string; status: string; decision_status: string | null; decision_reason: string;
}
interface RunDetail extends RunRow { engine_version: string; snapshot: Record<string, unknown>; results: Result[]; proposals: Proposal[] }
interface Rule {
  id: number; rule_code: string; rule_version: number; proposal_type: string; title: string; formula_type: string; formula_description: string; parameters: Record<string, unknown>;
  machine_type_code: string | null; basis_note: string; approval_status: string; approved_by: string; executable: boolean;
}

const STATUS_CLS: Record<string, string> = {
  DRAFT: "bg-slate-500/20 text-slate-500", READY: "pg-adv", REVIEWED: "pg-known", APPROVED: "pg-ok", ARCHIVED: "bg-slate-500/20 text-slate-400",
  CALCULATED: "pg-ok", NEEDS_INPUT: "pg-adv", NOT_APPLICABLE: "bg-slate-500/20 text-slate-400", SELECTED: "pg-known", REJECTED: "bg-red-500/20 text-red-600",
  MISSING_BASELINE: "bg-red-500/20 text-red-600", UNIT_MISMATCH: "bg-red-500/20 text-red-600", SCOPE_MISMATCH: "bg-red-500/20 text-red-600", PARTIAL_SOURCE: "pg-adv",
  RETIRED: "bg-slate-500/20 text-slate-400",
};
const Chip = ({ s }: { s: string }) => <span className={`pg-chip ${STATUS_CLS[s] ?? ""}`}>{s}</span>;
const PTYPE_LABEL: Record<string, string> = { LABOR_RECRUITMENT: "Tuyển lao động", MACHINE_PURCHASE: "Mua máy", TECHNOLOGY_ADOPTION: "Áp dụng công nghệ", CAPACITY_CHANGE: "Đổi năng lực" };

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4" role="dialog" aria-modal="true" onClick={onClose}>
      <div className={`my-4 w-full ${wide ? "max-w-6xl" : "max-w-2xl"} rounded-2xl bg-white p-6 text-slate-900 shadow-xl`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between"><h3 className="text-lg font-bold">{title}</h3><button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Đóng">✕</button></div>
        {children}
      </div>
    </div>
  );
}
const F = ({ label, children }: { label: string; children: React.ReactNode }) => <label className="block text-xs text-slate-500">{label}{children}</label>;
const Notice = ({ msg }: { msg: Msg }) => (msg ? <p className={`mb-3 rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p> : null);
const J = ({ v }: { v: unknown }) => <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 text-xs text-slate-100">{JSON.stringify(v, null, 2)}</pre>;

/** Roadmap Simulation (Task 5 — Issue #11): scenario → version → milestone/target → run → gap + proposals. Không optimizer, không ranking. */
export default function Roadmap() {
  const { can } = useAuth();
  const perm = { manage: can("roadmap.manage"), run: can("roadmap.run"), approve: can("roadmap.approve") };
  const [opts, setOpts] = useState<Options | null>(null);
  const [rows, setRows] = useState<Scenario[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [msg, setMsg] = useState<Msg>(null);
  const [creating, setCreating] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const load = useCallback(async () => setRows((await api.get<Scenario[]>(`${RES}/scenarios`)).data), []);
  useEffect(() => { api.get<Options>(`${RES}/options`).then((r) => setOpts(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) })); load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load]);
  return (
    <div className="space-y-3">
      <div>
        <h1 className="text-xl font-bold">ROADMAP SIMULATION</h1>
        <p className="text-xs text-slate-500">Scenario có version/milestone/target; mỗi lần chạy sinh Run bất biến với snapshot đầy đủ: baseline, target, gap, dữ liệu thiếu và proposal. Đây là nền tính toán minh bạch — không tối ưu toàn cục, không xếp hạng, không tự chọn phương án.</p>
      </div>
      <Notice msg={msg} />
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex-1" />
        <button onClick={() => setRulesOpen(true)} className={btn} data-testid="roadmap-rules-open">Rule registry</button>
        {perm.manage && <button onClick={() => setCreating(true)} className={primary} data-testid="roadmap-scenario-add">+ Scenario</button>}
      </div>
      <div className="grid gap-3 lg:grid-cols-[320px_1fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-2" data-testid="roadmap-scenario-list">
          {rows.map((s) => (
            <button key={s.id} onClick={() => setSel(s.id)} className={`mb-1 block w-full rounded-xl px-3 py-2 text-left text-sm hover:bg-slate-500/10 ${sel === s.id ? "bg-slate-500/10" : ""}`} data-testid={`roadmap-scenario-${s.id}`}>
              <div className="flex items-center gap-2"><span className="font-mono text-xs">{s.scenario_code}</span><Chip s={s.status} /></div>
              <div className="font-semibold">{s.name}</div>
              <div className="text-[11px] text-slate-400">{s.scope_type === "TOTAL" ? "Tổng công ty" : s.scope_value} · {s.owner}</div>
            </button>
          ))}
          {rows.length === 0 && <p className="p-4 text-center text-sm text-slate-400">Chưa có scenario nào.</p>}
        </div>
        <div>{sel !== null && opts ? <ScenarioDetail key={sel} id={sel} opts={opts} perm={perm} onChanged={() => void load()} setMsg={setMsg} /> : <p className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">Chọn một scenario để xem version, milestone và kết quả mô phỏng.</p>}</div>
      </div>
      {creating && opts && <ScenarioForm opts={opts} onClose={() => setCreating(false)} onDone={(id) => { setCreating(false); void load(); setSel(id); }} setMsg={setMsg} />}
      {rulesOpen && opts && <RulesModal opts={opts} perm={perm} onClose={() => setRulesOpen(false)} setMsg={setMsg} />}
    </div>
  );
}

function ScenarioForm({ opts, onClose, onDone, setMsg }: { opts: Options; onClose: () => void; onDone: (id: number) => void; setMsg: (m: Msg) => void }) {
  const [d, setD] = useState({ name: "", description: "", scope_type: "TOTAL", scope_value: "" });
  const [factories, setFactories] = useState<string[]>(["XN1", "XN2", "XN3"]);
  useEffect(() => { setFactories(["XN1", "XN2", "XN3"]); }, []);
  const submit = async () => {
    try { const r = await api.post<Scenario>(`${RES}/scenarios`, d); setMsg({ ok: true, text: `Đã tạo ${r.data.scenario_code}.` }); onDone(r.data.id); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  return (
    <Modal title="Roadmap Scenario mới" onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2"><F label="Tên"><input className={inp} value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} data-testid="roadmap-scenario-name" /></F></div>
        <F label="Scope"><select className={inp} value={d.scope_type} onChange={(e) => setD({ ...d, scope_type: e.target.value, scope_value: "" })}>{opts.scope_types.map((s) => <option key={s} value={s}>{s === "TOTAL" ? "Tổng công ty" : "Xí nghiệp"}</option>)}</select></F>
        <F label="Xí nghiệp">{d.scope_type === "FACTORY" ? <select className={inp} value={d.scope_value} onChange={(e) => setD({ ...d, scope_value: e.target.value })}><option value="">—</option>{factories.map((f) => <option key={f}>{f}</option>)}</select> : <input className={inp} disabled value="—" />}</F>
        <div className="col-span-2"><F label="Mô tả"><input className={inp} value={d.description} onChange={(e) => setD({ ...d, description: e.target.value })} /></F></div>
      </div>
      <div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
        <button onClick={submit} disabled={!d.name.trim() || (d.scope_type === "FACTORY" && !d.scope_value)} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="roadmap-scenario-save">Tạo</button></div>
    </Modal>
  );
}

function ScenarioDetail({ id, opts, perm, onChanged, setMsg }: { id: number; opts: Options; perm: { manage: boolean; run: boolean; approve: boolean }; onChanged: () => void; setMsg: (m: Msg) => void }) {
  const [s, setS] = useState<Scenario | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const load = useCallback(async () => {
    const r = await api.get<Scenario>(`${RES}/scenarios/${id}`);
    setS(r.data);
    setVersionId((cur) => cur ?? (r.data.versions && r.data.versions.length ? r.data.versions[r.data.versions.length - 1].id : null));
  }, [id]);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); setMsg({ ok: true, text: ok }); await load(); onChanged(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  if (!s) return <p className="text-sm text-slate-400">Đang tải...</p>;
  const move = (to: string) => {
    let reason = "";
    if (to === "ARCHIVED") { reason = window.prompt("Lý do lưu trữ scenario? (bắt buộc)") ?? ""; if (!reason.trim()) return; }
    void act(() => api.post(`${RES}/scenarios/${id}/transition`, { to_status: to, reason }), `Scenario → ${to}.`);
  };
  return (
    <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-bold">{s.scenario_code} · {s.name}</h2><Chip s={s.status} />
        <span className="text-xs text-slate-400">{s.scope_type === "TOTAL" ? "Tổng công ty" : s.scope_value} · owner {s.owner}</span>
        <span className="flex-1" />
        {perm.manage && s.allowed_transitions.map((to) => <button key={to} onClick={() => move(to)} disabled={to === "APPROVED" && !perm.approve} title={to === "APPROVED" && !perm.approve ? "Cần quyền roadmap.approve" : ""} className={btn} data-testid={`roadmap-scenario-to-${to}`}>→ {to}</button>)}
      </div>
      {s.description && <p className="text-xs text-slate-500">{s.description}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-bold uppercase text-slate-400">Version</span>
        {(s.versions ?? []).map((v) => <button key={v.id} onClick={() => setVersionId(v.id)} className={`${btn} ${versionId === v.id ? "bg-slate-500/20" : ""}`} data-testid={`roadmap-version-${v.id}`}>v{v.version_no} · {v.status}</button>)}
        {perm.manage && s.status !== "ARCHIVED" && (
          <>
            <button onClick={() => void act(async () => { const r = await api.post<Version>(`${RES}/scenarios/${id}/versions`, {}); setVersionId(r.data.id); }, "Đã tạo version mới (Draft).")} className={btn} data-testid="roadmap-version-new">+ Version trống</button>
            {versionId !== null && <button onClick={() => void act(async () => { const r = await api.post<Version>(`${RES}/scenarios/${id}/versions`, { copy_from_version_id: versionId }); setVersionId(r.data.id); }, "Đã copy thành version mới (Draft) — đổi input = version mới.")} className={btn} data-testid="roadmap-version-copy">Copy version đang xem</button>}
          </>
        )}
      </div>
      {versionId !== null ? <VersionPanel key={versionId} versionId={versionId} opts={opts} perm={perm} onChanged={() => { void load(); onChanged(); }} setMsg={setMsg} /> : <p className="text-sm text-slate-400">Scenario chưa có version. Tạo version để nhập milestone/target.</p>}
    </div>
  );
}

function VersionPanel({ versionId, opts, perm, onChanged, setMsg }: { versionId: number; opts: Options; perm: { manage: boolean; run: boolean; approve: boolean }; onChanged: () => void; setMsg: (m: Msg) => void }) {
  const [v, setV] = useState<Version | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [cmp, setCmp] = useState<number[]>([]);
  const [showCmp, setShowCmp] = useState(false);
  const [msForm, setMsForm] = useState(false);
  const [tgtFor, setTgtFor] = useState<Milestone | null>(null);
  const [link, setLink] = useState({ link_type: "FUTURE_CANDIDATE", ref_id: "" });
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [vd, rr] = await Promise.all([api.get<Version>(`${RES}/versions/${versionId}`), api.get<RunRow[]>(`${RES}/versions/${versionId}/runs`)]);
    setV(vd.data); setRuns(rr.data);
  }, [versionId]);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); setMsg({ ok: true, text: ok }); await load(); onChanged(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  if (!v) return <p className="text-sm text-slate-400">Đang tải version...</p>;
  const runSim = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ created: boolean; run: RunRow }>(`${RES}/versions/${versionId}/runs`);
      setMsg({ ok: true, text: r.data.created ? `Đã chạy simulation — Run #${r.data.run.run_no}.` : `Không có gì thay đổi so với Run #${r.data.run.run_no} (cùng version, baseline và rule) — dùng lại run cũ.` });
      setRunId(r.data.run.id); await load();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(false); }
  };
  const move = (to: string) => {
    let reason = "";
    if (to === "ARCHIVED") { reason = window.prompt("Lý do lưu trữ version? (bắt buộc)") ?? ""; if (!reason.trim()) return; }
    void act(() => api.post(`${RES}/versions/${versionId}/transition`, { to_status: to, reason }), to === "READY" ? "Đã chuyển READY — business inputs bị khóa." : `Version → ${to}.`);
  };
  const runnable = v.status === "READY" || v.status === "REVIEWED";
  return (
    <div className="space-y-3 border-t border-slate-100 pt-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <b>Version {v.version_no}</b><Chip s={v.status} />
        {v.locked_at && <span className="text-slate-400">khóa inputs từ {dateVi(v.locked_at.slice(0, 10))}</span>}
        {v.copied_from_version_id && <span className="text-slate-400">· copy từ #{v.copied_from_version_id}</span>}
        <span className="flex-1" />
        {perm.manage && v.allowed_transitions.map((to) => <button key={to} onClick={() => move(to)} disabled={to === "APPROVED" && !perm.approve} title={to === "APPROVED" && !perm.approve ? "Cần quyền roadmap.approve" : ""} className={btn} data-testid={`roadmap-to-${to}`}>→ {to}</button>)}
        {perm.run && <button onClick={runSim} disabled={busy || !runnable} title={runnable ? "" : "Chỉ chạy trên version READY/REVIEWED"} className={primary} data-testid="roadmap-run">Chạy simulation</button>}
      </div>
      {!v.editable && <p className="text-[11px] text-amber-700">Version {v.status} — business inputs đã khóa. Muốn đổi target/milestone, hãy copy thành version mới.</p>}

      <div className="flex items-center gap-2"><h3 className="text-sm font-bold">Milestone & target</h3><span className="flex-1" />
        {perm.manage && v.editable && <button onClick={() => setMsForm(true)} className={btn} data-testid="roadmap-milestone-add">+ Milestone</button>}</div>
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full text-xs" data-testid="roadmap-milestone-table">
          <thead><tr><th className={th}>Milestone</th><th className={th}>Ngày</th><th className={th}>Metric</th><th className={th}>Loại</th><th className={`${th} text-right`}>Giá trị</th><th className={th}>Đơn vị</th><th className={th}>Kỳ</th><th className={th}>Baseline basis</th><th className={th}>Kỳ tham chiếu</th><th className={th}>Scope</th><th /></tr></thead>
          <tbody>
            {v.milestones.flatMap((m) => (m.targets.length ? m.targets : [null]).map((t, i) => (
              <tr key={`${m.id}-${t?.id ?? "none"}`} className="border-t border-slate-100">
                <td className="px-3 py-1.5 font-mono">{i === 0 ? `${m.sequence}. ${m.code}` : ""}</td><td className="px-3">{i === 0 ? dateVi(m.target_date) : ""}</td>
                {t ? (<>
                  <td className="px-3">{t.metric_code}</td><td className="px-3">{t.target_kind === "INCREMENT" ? "Tăng thêm" : "Tuyệt đối"}</td><td className="px-3 text-right">{num(t.target_value)}</td><td className="px-3">{t.unit}</td>
                  <td className="px-3">{t.period_type === "MONTH" ? `${t.period_year}-${String(t.period_month).padStart(2, "0")}` : t.period_year}</td>
                  <td className="px-3">{t.baseline_basis ?? <span className="text-amber-600">chưa chọn</span>}</td>
                  <td className="px-3">{t.baseline_ref_year ? (t.period_type === "MONTH" ? `${t.baseline_ref_year}-${String(t.baseline_ref_month).padStart(2, "0")}` : t.baseline_ref_year) : "cùng kỳ"}</td>
                  <td className="px-3">{t.scope_type === "TOTAL" ? "TOTAL" : t.scope_value}</td>
                  <td className="px-3 text-right">{perm.manage && v.editable && <button onClick={() => void act(() => api.delete(`${RES}/targets/${t.id}`), "Đã xóa target.")} className="text-red-500 hover:underline">Xóa</button>}</td>
                </>) : <td colSpan={9} className="px-3 text-slate-400">Chưa có target</td>}
                {!t && <td />}
              </tr>
            )).concat(perm.manage && v.editable ? [
              <tr key={`add-${m.id}`}><td colSpan={11} className="px-3 py-1 text-right"><button onClick={() => setTgtFor(m)} className="text-brand hover:underline" data-testid={`roadmap-target-add-${m.id}`}>+ Target cho {m.code}</button>
                <button onClick={() => void act(() => api.delete(`${RES}/milestones/${m.id}`), "Đã xóa milestone.")} className="ml-3 text-red-500 hover:underline">Xóa milestone</button></td></tr>] : []))}
            {v.milestones.length === 0 && <tr><td colSpan={11} className="py-4 text-center text-slate-400">Chưa có milestone.</td></tr>}
          </tbody>
        </table>
      </div>

      <h3 className="text-sm font-bold">Liên kết công nghệ (chỉ link + snapshot evidence — không sinh số)</h3>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {v.technology_links.map((k) => <span key={k.id} className="rounded-full border border-slate-300 px-3 py-1">{k.link_type === "FUTURE_CANDIDATE" ? "Candidate" : "Process version"} #{k.ref_id}{perm.manage && v.editable && <button onClick={() => void act(() => api.delete(`${RES}/technology-links/${k.id}`), "Đã bỏ liên kết.")} className="ml-2 text-red-500">✕</button>}</span>)}
        {v.technology_links.length === 0 && <span className="text-slate-400">Chưa liên kết.</span>}
        {perm.manage && v.editable && (
          <>
            <select className={`${inp} w-44`} value={link.link_type} onChange={(e) => setLink({ ...link, link_type: e.target.value })}><option value="FUTURE_CANDIDATE">Future candidate id</option><option value="PROCESS_VERSION">Technology process version id</option></select>
            <input className={`${inp} w-24`} type="number" placeholder="id" value={link.ref_id} onChange={(e) => setLink({ ...link, ref_id: e.target.value })} />
            <button disabled={!link.ref_id} onClick={() => void act(() => api.post(`${RES}/versions/${versionId}/technology-links`, { link_type: link.link_type, ref_id: Number(link.ref_id) }), "Đã liên kết.")} className={btn}>+ Liên kết</button>
          </>
        )}
      </div>

      <div className="flex items-center gap-2"><h3 className="text-sm font-bold">Lịch sử Run</h3><span className="flex-1" />
        {cmp.length === 2 && <button onClick={() => setShowCmp(true)} className={btn} data-testid="roadmap-compare">So sánh 2 run</button>}</div>
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full text-xs" data-testid="roadmap-run-table"><thead><tr><th className={th} /><th className={th}>Run</th><th className={th}>Thời điểm</th><th className={th}>Hoàn chỉnh</th><th className={th}>Target</th><th className={th}>Proposal</th><th className={th}>Cờ dữ liệu</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-500/5 ${runId === r.id ? "bg-slate-500/10" : ""}`} onClick={() => setRunId(r.id)} data-testid={`roadmap-run-${r.id}`}>
                <td className="px-3 py-1.5" onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Chọn run ${r.run_no} để so sánh`} checked={cmp.includes(r.id)} onChange={() => setCmp((c) => c.includes(r.id) ? c.filter((x) => x !== r.id) : [...c, r.id].slice(-2))} /></td>
                <td className="px-3">#{r.run_no}</td><td className="px-3">{dateVi(r.created_at.slice(0, 10))} {r.created_at.slice(11, 16)} · {r.created_by}</td><td className="px-3"><Chip s={r.summary.completeness === "COMPLETE" ? "CALCULATED" : r.summary.completeness === "PARTIAL" ? "PARTIAL_SOURCE" : "NEEDS_INPUT"} /> {r.summary.completeness}</td>
                <td className="px-3">{Object.entries(r.summary.target_result_counts).map(([k, n]) => `${k}:${n}`).join(" ")}</td><td className="px-3">{Object.entries(r.summary.proposal_status_counts).map(([k, n]) => `${k}:${n}`).join(" ")}</td>
                <td className="px-3 text-[11px] text-amber-700">{r.summary.data_quality_flags.join(", ") || "—"}</td>
              </tr>
            ))}
            {runs.length === 0 && <tr><td colSpan={7} className="py-4 text-center text-slate-400">Chưa chạy simulation lần nào.</td></tr>}
          </tbody>
        </table>
      </div>
      {runId !== null && <RunResult key={runId} runId={runId} perm={perm} setMsg={setMsg} />}
      {msForm && <MilestoneForm versionId={versionId} onClose={() => setMsForm(false)} onDone={() => { setMsForm(false); void load(); }} setMsg={setMsg} />}
      {tgtFor && <TargetForm milestone={tgtFor} version={v} opts={opts} onClose={() => setTgtFor(null)} onDone={() => { setTgtFor(null); void load(); }} setMsg={setMsg} />}
      {showCmp && cmp.length === 2 && <CompareModal a={cmp[0]} b={cmp[1]} onClose={() => setShowCmp(false)} setMsg={setMsg} />}
    </div>
  );
}

function MilestoneForm({ versionId, onClose, onDone, setMsg }: { versionId: number; onClose: () => void; onDone: () => void; setMsg: (m: Msg) => void }) {
  const [d, setD] = useState({ code: "", name: "", target_date: "" });
  const submit = async () => { try { await api.post(`${RES}/versions/${versionId}/milestones`, d); setMsg({ ok: true, text: "Đã thêm milestone." }); onDone(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  return (
    <Modal title="Milestone mới" onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <F label="Mã (duy nhất trong version)"><input className={inp} value={d.code} onChange={(e) => setD({ ...d, code: e.target.value })} data-testid="roadmap-ms-code" /></F>
        <F label="Ngày mục tiêu"><input type="date" className={inp} value={d.target_date} onChange={(e) => setD({ ...d, target_date: e.target.value })} data-testid="roadmap-ms-date" /></F>
        <div className="col-span-2"><F label="Tên"><input className={inp} value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></F></div>
      </div>
      <div className="mt-5 flex justify-end gap-2"><button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
        <button onClick={submit} disabled={!d.code.trim() || !d.target_date} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="roadmap-ms-save">Lưu</button></div>
    </Modal>
  );
}

function TargetForm({ milestone, version, opts, onClose, onDone, setMsg }: { milestone: Milestone; version: Version; opts: Options; onClose: () => void; onDone: () => void; setMsg: (m: Msg) => void }) {
  const y = Number(milestone.target_date.slice(0, 4)), mo = Number(milestone.target_date.slice(5, 7));
  const [d, setD] = useState({ metric_code: "REVENUE", target_kind: "ABSOLUTE", target_value: "", unit: "USD", period_type: "MONTH", period_year: String(y), period_month: String(mo), baseline_basis: "", ref_year: "", ref_month: "", note: "" });
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const bases = opts.baseline_bases[d.metric_code] ?? [];
  const canon = opts.canonical_units[d.metric_code];
  const refY = d.ref_year || d.period_year, refM = d.ref_month || d.period_month;
  const showPreview = async () => {
    try {
      const r = await api.get(`${RES}/baseline-preview`, { params: { metric_code: d.metric_code, baseline_basis: d.baseline_basis, period_type: d.period_type, year: Number(refY), month: d.period_type === "MONTH" ? Number(refM) : undefined, scope_type: version.scope_type, scope_value: version.scope_value } });
      setPreview(r.data);
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const submit = async () => {
    try {
      await api.post(`${RES}/milestones/${milestone.id}/targets`, {
        metric_code: d.metric_code, target_kind: d.target_kind, target_value: Number(d.target_value), unit: d.unit, period_type: d.period_type, period_year: Number(d.period_year),
        period_month: d.period_type === "MONTH" ? Number(d.period_month) : undefined, baseline_basis: d.baseline_basis || undefined,
        baseline_ref_year: d.ref_year ? Number(d.ref_year) : undefined, baseline_ref_month: d.ref_year && d.period_type === "MONTH" ? Number(d.ref_month) : undefined, note: d.note || undefined,
      });
      setMsg({ ok: true, text: "Đã thêm target." }); onDone();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  return (
    <Modal title={`Target cho milestone ${milestone.code}`} onClose={onClose} wide>
      <p className="text-xs text-slate-500">Scope mặc định = scope scenario ({version.scope_type === "TOTAL" ? "Tổng công ty" : version.scope_value}). "Tăng thêm" = baseline + giá trị; "Tuyệt đối" = giá trị là mốc cần đạt. Không quy đổi đơn vị: {d.metric_code} chỉ nhận đơn vị <b>{canon}</b>. Kỳ tương lai không có dữ liệu cần chọn kỳ tham chiếu lịch sử tường minh.</p>
      <div className="mt-3 grid grid-cols-4 gap-3">
        <F label="Metric"><select className={inp} value={d.metric_code} onChange={(e) => setD({ ...d, metric_code: e.target.value, unit: opts.canonical_units[e.target.value], baseline_basis: "" })} data-testid="roadmap-t-metric">{opts.metric_codes.map((m) => <option key={m}>{m}</option>)}</select></F>
        <F label="Loại target"><select className={inp} value={d.target_kind} onChange={(e) => setD({ ...d, target_kind: e.target.value })} data-testid="roadmap-t-kind"><option value="ABSOLUTE">Tuyệt đối</option><option value="INCREMENT">Tăng thêm</option></select></F>
        <F label="Giá trị"><input type="number" className={inp} value={d.target_value} onChange={(e) => setD({ ...d, target_value: e.target.value })} data-testid="roadmap-t-value" /></F>
        <F label={`Đơn vị (chuẩn ${canon})`}><input className={inp} value={d.unit} onChange={(e) => setD({ ...d, unit: e.target.value })} data-testid="roadmap-t-unit" /></F>
        <F label="Kỳ"><select className={inp} value={d.period_type} onChange={(e) => setD({ ...d, period_type: e.target.value })}>{opts.period_types.map((p) => <option key={p}>{p}</option>)}</select></F>
        <F label="Năm"><input type="number" className={inp} value={d.period_year} onChange={(e) => setD({ ...d, period_year: e.target.value })} /></F>
        <F label="Tháng">{d.period_type === "MONTH" ? <input type="number" className={inp} value={d.period_month} onChange={(e) => setD({ ...d, period_month: e.target.value })} /> : <input className={inp} disabled value="—" />}</F>
        <F label="Baseline basis (bắt buộc để tính)"><select className={inp} value={d.baseline_basis} onChange={(e) => setD({ ...d, baseline_basis: e.target.value })} data-testid="roadmap-t-basis"><option value="">— chưa chọn (NEEDS_INPUT) —</option>{bases.map((b) => <option key={b}>{b}</option>)}</select></F>
        <F label="Kỳ tham chiếu: năm (trống = cùng kỳ)"><input type="number" className={inp} value={d.ref_year} onChange={(e) => setD({ ...d, ref_year: e.target.value })} /></F>
        <F label="Kỳ tham chiếu: tháng">{d.period_type === "MONTH" ? <input type="number" className={inp} value={d.ref_month} onChange={(e) => setD({ ...d, ref_month: e.target.value })} disabled={!d.ref_year} /> : <input className={inp} disabled value="—" />}</F>
        <div className="col-span-2"><F label="Ghi chú nguồn/giả định"><input className={inp} value={d.note} onChange={(e) => setD({ ...d, note: e.target.value })} /></F></div>
      </div>
      {d.metric_code === "OUTPUT_QTY" && <p className="mt-2 text-[11px] text-amber-700">OUTPUT_QTY = PACK_QTY (đóng gói/FG). Chỉ scope Tổng công ty tính được gap; theo xí nghiệp chưa đủ dữ liệu (PARTIAL_SOURCE).</p>}
      {preview && <div className="mt-3"><J v={{ status: preview.status, value: preview.value, unit: preview.unit, flags: preview.flags, missing_inputs: preview.missing_inputs, source_meta: preview.source_meta }} /></div>}
      <div className="mt-5 flex justify-end gap-2"><button onClick={showPreview} disabled={!d.baseline_basis} className={btn} data-testid="roadmap-t-preview">Xem baseline hiện có</button>
        <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
        <button onClick={submit} disabled={d.target_value === "" || !d.unit.trim()} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="roadmap-t-save">Lưu target</button></div>
    </Modal>
  );
}

function RunResult({ runId, perm, setMsg }: { runId: number; perm: { manage: boolean }; setMsg: (m: Msg) => void }) {
  const [r, setR] = useState<RunDetail | null>(null);
  const [drawer, setDrawer] = useState<{ title: string; data: unknown } | null>(null);
  const load = useCallback(async () => setR((await api.get<RunDetail>(`${RES}/runs/${runId}`)).data), [runId]);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  if (!r) return <p className="text-sm text-slate-400">Đang tải kết quả...</p>;
  const fresh = (r.snapshot.source_freshness ?? {}) as { latest_success?: { started_at?: string; status?: string } | null; last_attempt?: { started_at?: string; status?: string } | null; source_age_hours?: number | null };
  const decide = async (p: Proposal, decision: string) => {
    const reason = window.prompt(`Lý do ${decision === "SELECTED" ? "chọn" : "loại"} proposal này? (bắt buộc — chỉ ghi nhận quyết định, KHÔNG thực thi mua/tuyển/đổi năng lực)`) ?? "";
    if (!reason.trim()) return;
    try { await api.post(`${RES}/proposals/${p.id}/decision`, { decision, reason }); setMsg({ ok: true, text: `Đã ghi nhận ${decision}.` }); await load(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const flags = r.summary.data_quality_flags;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 p-3" data-testid="roadmap-run-result">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <b>Run #{r.run_no}</b><span className="text-slate-400">engine {r.engine_version} · bất biến</span><span className="flex-1" />
        <button onClick={() => setDrawer({ title: "Snapshot đầu vào của Run", data: r.snapshot })} className={btn} data-testid="roadmap-snapshot">Evidence / snapshot</button>
      </div>
      {flags.length > 0 && <p className="rounded-lg border border-amber-300/60 px-3 py-2 text-xs text-amber-700" data-testid="roadmap-flags">Cờ chất lượng dữ liệu: {flags.join(", ")}.{flags.includes("SOURCE_STALE_OR_LAST_SYNC_FAILED") && ` Đồng bộ thành công gần nhất: ${fresh.latest_success?.started_at?.slice(0, 16) ?? "chưa có"} (${fresh.source_age_hours ?? "?"} giờ trước); lần thử gần nhất: ${fresh.last_attempt?.status ?? "?"}.`}</p>}
      <div className="overflow-x-auto"><table className="w-full text-xs" data-testid="roadmap-result-table">
        <thead><tr><th className={th}>Milestone</th><th className={th}>Metric / kỳ</th><th className={`${th} text-right`}>Baseline</th><th className={`${th} text-right`}>Target hiệu lực</th><th className={`${th} text-right`}>Gap</th><th className={th}>Trạng thái</th><th className={th}>Đủ/thiếu dữ liệu</th><th /></tr></thead>
        <tbody>{r.results.map((x) => (
          <tr key={x.id} className="border-t border-slate-100 align-top">
            <td className="px-3 py-1.5 font-mono">{x.milestone_code}</td>
            <td className="px-3">{x.metric_code}{x.output_definition ? ` (${x.output_definition})` : ""} · {x.period_label}{x.baseline_period_label !== x.period_label ? <span className="text-slate-400"> (tham chiếu {x.baseline_period_label})</span> : ""}</td>
            <td className="px-3 text-right">{x.baseline_value === null ? <span className="text-slate-400">N/A</span> : `${num(x.baseline_value)} ${x.baseline_unit}`}<div className="text-[10px] text-slate-400">{x.baseline_basis ?? "—"}</div></td>
            <td className="px-3 text-right">{x.effective_target === null ? <span className="text-slate-400">N/A</span> : `${num(x.effective_target)} ${x.unit}`}<div className="text-[10px] text-slate-400">{x.target_kind === "INCREMENT" ? `+${num(x.increment_value)} (tăng thêm)` : "tuyệt đối"}</div></td>
            <td className={`px-3 text-right font-semibold ${x.gap !== null && x.gap <= 0 ? "text-green-700" : ""}`}>{x.gap === null ? <span className="text-slate-400">N/A</span> : num(x.gap)}</td>
            <td className="px-3"><Chip s={x.result_status} /></td>
            <td className="px-3">{x.completeness}{x.data_quality_flags.length > 0 && <div className="text-[10px] text-amber-700">{x.data_quality_flags.join(", ")}</div>}{x.missing_inputs.length > 0 && <ul className="list-disc pl-4 text-[11px] text-red-600">{x.missing_inputs.map((m) => <li key={m}>{m}</li>)}</ul>}</td>
            <td className="px-3"><button onClick={() => setDrawer({ title: `Evidence — ${x.milestone_code} ${x.metric_code}`, data: { source_identity: x.source_identity, source_meta: x.source_meta } })} className="text-brand hover:underline">Evidence</button></td>
          </tr>
        ))}</tbody></table></div>

      <h4 className="text-sm font-bold">Proposal (không xếp hạng, không tự chọn)</h4>
      <div className="overflow-x-auto"><table className="w-full text-xs" data-testid="roadmap-proposal-table">
        <thead><tr><th className={th}>Milestone</th><th className={th}>Loại</th><th className={th}>Trạng thái</th><th className={`${th} text-right`}>Số lượng</th><th className={th}>Rule</th><th className={th}>Lý do / thiếu input</th><th /></tr></thead>
        <tbody>{r.proposals.map((p) => (
          <tr key={p.id} className="border-t border-slate-100 align-top" data-testid={`roadmap-proposal-${p.id}`}>
            <td className="px-3 py-1.5 font-mono">{p.milestone_code}</td><td className="px-3">{PTYPE_LABEL[p.proposal_type] ?? p.proposal_type}</td>
            <td className="px-3"><Chip s={p.status} />{p.decision_status && <div className="text-[10px] text-slate-400">tính toán: {p.calc_status}</div>}</td>
            <td className="px-3 text-right">{p.quantity === null ? <span className="text-slate-400">N/A</span> : `${num(p.quantity)} ${p.unit}`}</td><td className="px-3 font-mono text-[11px]">{p.calculation_rule_version}</td>
            <td className="px-3">{p.rationale}{p.missing_inputs.length > 0 && <ul className="list-disc pl-4 text-[11px] text-red-600">{p.missing_inputs.map((m) => <li key={m}>{m}</li>)}</ul>}{p.decision_reason && <div className="text-[11px] text-slate-500">Quyết định: {p.decision_reason}</div>}</td>
            <td className="whitespace-nowrap px-3 text-right">
              <button onClick={() => setDrawer({ title: `Evidence — ${p.proposal_type}`, data: { input_snapshot: p.input_snapshot, evidence_refs: p.evidence_refs, missing_inputs: p.missing_inputs, calculation_rule_version: p.calculation_rule_version } })} className="text-brand hover:underline">Evidence</button>
              {perm.manage && <><button onClick={() => void decide(p, "SELECTED")} disabled={p.decision_status === "SELECTED"} className="ml-2 text-green-700 hover:underline disabled:opacity-40" data-testid={`roadmap-select-${p.id}`}>Chọn</button>
                <button onClick={() => void decide(p, "REJECTED")} disabled={p.decision_status === "REJECTED"} className="ml-2 text-red-600 hover:underline disabled:opacity-40">Loại</button></>}
            </td>
          </tr>
        ))}</tbody></table></div>
      {drawer && <Modal title={drawer.title} onClose={() => setDrawer(null)} wide><J v={drawer.data} /></Modal>}
    </div>
  );
}

function CompareModal({ a, b, onClose, setMsg }: { a: number; b: number; onClose: () => void; setMsg: (m: Msg) => void }) {
  interface Side { baseline: number | null; effective_target: number | null; gap: number | null; status: string }
  const [c, setC] = useState<{ run_a: RunRow; run_b: RunRow; targets: { milestone_code: string; metric_code: string; period_label: string; baseline_basis: string | null; a: Side | null; b: Side | null; changed: boolean }[]; proposals: { milestone_code: string; proposal_type: string; rule: string; a: { status: string; quantity: number | null } | null; b: { status: string; quantity: number | null } | null }[] } | null>(null);
  useEffect(() => { api.get(`${RES}/runs/${a}/compare-with/${b}`).then((r) => setC(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [a, b, setMsg]);
  const cell = (s: Side | null) => (s ? `${s.baseline === null ? "N/A" : num(s.baseline)} → gap ${s.gap === null ? "N/A" : num(s.gap)} (${s.status})` : "—");
  return (
    <Modal title="So sánh 2 Run (không xếp hạng)" onClose={onClose} wide>
      {!c && <p className="text-xs text-slate-400">Đang tải...</p>}
      {c && (
        <div className="space-y-3 text-xs">
          <p>Run #{c.run_a.run_no} (A) ↔ Run #{c.run_b.run_no} (B)</p>
          <table className="w-full"><thead><tr><th className={th}>Milestone / metric / kỳ</th><th className={th}>A</th><th className={th}>B</th><th className={th}>Đổi</th></tr></thead>
            <tbody>{c.targets.map((t, i) => <tr key={i} className="border-t border-slate-100"><td className="px-3 py-1.5">{t.milestone_code} · {t.metric_code} · {t.period_label} {t.baseline_basis ?? ""}</td><td className="px-3">{cell(t.a)}</td><td className="px-3">{cell(t.b)}</td><td className="px-3">{t.changed ? "có" : "không"}</td></tr>)}</tbody></table>
          <table className="w-full"><thead><tr><th className={th}>Proposal</th><th className={th}>A</th><th className={th}>B</th></tr></thead>
            <tbody>{c.proposals.map((p, i) => <tr key={i} className="border-t border-slate-100"><td className="px-3 py-1.5">{p.milestone_code} · {PTYPE_LABEL[p.proposal_type] ?? p.proposal_type} · {p.rule}</td><td className="px-3">{p.a ? `${p.a.status}${p.a.quantity !== null ? ` (${num(p.a.quantity)})` : ""}` : "—"}</td><td className="px-3">{p.b ? `${p.b.status}${p.b.quantity !== null ? ` (${num(p.b.quantity)})` : ""}` : "—"}</td></tr>)}</tbody></table>
        </div>
      )}
    </Modal>
  );
}

function RulesModal({ opts, perm, onClose, setMsg }: { opts: Options; perm: { manage: boolean; approve: boolean }; onClose: () => void; setMsg: (m: Msg) => void }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [d, setD] = useState({ rule_code: "", proposal_type: "LABOR_RECRUITMENT", formula_type: "", formula_description: "", parameters: "", machine_type_code: "", basis_note: "" });
  const load = useCallback(async () => setRules((await api.get<Rule[]>(`${RES}/rules`)).data), []);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); setMsg({ ok: true, text: ok }); await load(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  const create = async () => {
    let parameters: Record<string, unknown> | undefined;
    if (d.parameters.trim()) { try { parameters = JSON.parse(d.parameters); } catch { setMsg({ ok: false, text: "parameters phải là JSON object hợp lệ" }); return; } }
    await act(async () => { await api.post(`${RES}/rules`, { rule_code: d.rule_code, proposal_type: d.proposal_type, formula_type: d.formula_type || undefined, formula_description: d.formula_description, parameters, machine_type_code: d.machine_type_code || undefined, basis_note: d.basis_note }); setD({ ...d, rule_code: "", parameters: "" }); }, "Đã tạo rule (Draft).");
  };
  return (
    <Modal title="Rule registry — metadata & phê duyệt (chưa thực thi)" onClose={onClose} wide>
      <p className="text-xs text-slate-500">Task 5 chỉ lưu <b>metadata, evidence, version và trạng thái duyệt</b> của rule. Rule KHÔNG được thực thi: chưa có công thức/adapter tính toán nào được business duyệt, nên proposal Labor/Machine luôn ở trạng thái NEEDS_INPUT dù rule đã APPROVED. Rule APPROVED bất biến — sửa = version mới. Không có rule nào được cấu hình sẵn.</p>
      <div className="mt-3 max-h-72 overflow-y-auto rounded-xl border border-slate-200">
        <table className="w-full text-xs" data-testid="roadmap-rule-table"><thead><tr><th className={th}>Rule</th><th className={th}>Loại</th><th className={th}>Mô tả (metadata)</th><th className={th}>Căn cứ</th><th className={th}>Trạng thái</th><th /></tr></thead>
          <tbody>{rules.map((r) => (
            <tr key={r.id} className="border-t border-slate-100 align-top"><td className="px-3 py-1.5 font-mono">{r.rule_code}@v{r.rule_version}<div className="text-[10px] text-slate-400">{r.formula_type}</div></td><td className="px-3">{PTYPE_LABEL[r.proposal_type]}{r.machine_type_code ? ` (${r.machine_type_code})` : ""}</td>
              <td className="px-3">{r.formula_description || <span className="text-amber-600">chưa có</span>}{Object.keys(r.parameters).length > 0 && <div className="font-mono text-[10px] text-slate-400">{JSON.stringify(r.parameters)}</div>}<div className="text-[10px] text-amber-700">không thực thi</div></td>
              <td className="px-3">{r.basis_note || <span className="text-amber-600">chưa có</span>}</td>
              <td className="px-3"><Chip s={r.approval_status} />{r.approved_by && <div className="text-[10px] text-slate-400">{r.approved_by}</div>}</td>
              <td className="whitespace-nowrap px-3 text-right">
                {perm.approve && r.approval_status === "DRAFT" && <button onClick={() => void act(() => api.post(`${RES}/rules/${r.id}/approve`), "Đã duyệt rule (metadata).")} className="text-green-700 hover:underline" data-testid={`roadmap-rule-approve-${r.id}`}>Duyệt</button>}
                {perm.approve && r.approval_status === "APPROVED" && <button onClick={() => { const reason = window.prompt("Lý do retire rule? (bắt buộc)") ?? ""; if (reason.trim()) void act(() => api.post(`${RES}/rules/${r.id}/retire`, { reason }), "Đã retire rule."); }} className="ml-2 text-red-600 hover:underline">Retire</button>}
                {perm.manage && r.approval_status !== "DRAFT" && <button onClick={() => void act(() => api.post(`${RES}/rules/${r.id}/new-version`), "Đã tạo version mới (Draft).")} className="ml-2 text-brand hover:underline">Version mới</button>}
              </td></tr>
          ))}{rules.length === 0 && <tr><td colSpan={6} className="py-4 text-center text-slate-400">Chưa có rule nào.</td></tr>}</tbody></table>
      </div>
      {perm.manage && (
        <div className="mt-3 grid grid-cols-4 gap-2 rounded-xl border border-slate-200 p-3">
          <F label="Mã rule"><input className={inp} value={d.rule_code} onChange={(e) => setD({ ...d, rule_code: e.target.value })} data-testid="roadmap-rule-code" /></F>
          <F label="Loại"><select className={inp} value={d.proposal_type} onChange={(e) => setD({ ...d, proposal_type: e.target.value })}>{opts.rule_proposal_types.map((t) => <option key={t} value={t}>{PTYPE_LABEL[t]}</option>)}</select></F>
          <F label="Formula type (metadata)"><input className={inp} value={d.formula_type} placeholder="UNSPECIFIED" onChange={(e) => setD({ ...d, formula_type: e.target.value })} /></F>
          <F label="Loại máy (chỉ Machine)"><input className={inp} value={d.machine_type_code} onChange={(e) => setD({ ...d, machine_type_code: e.target.value })} disabled={d.proposal_type !== "MACHINE_PURCHASE"} /></F>
          <div className="col-span-2"><F label="Mô tả rule (business sở hữu — bắt buộc để duyệt)"><input className={inp} value={d.formula_description} onChange={(e) => setD({ ...d, formula_description: e.target.value })} data-testid="roadmap-rule-desc" /></F></div>
          <div className="col-span-2"><F label="Căn cứ / nguồn (bắt buộc để duyệt)"><input className={inp} value={d.basis_note} onChange={(e) => setD({ ...d, basis_note: e.target.value })} /></F></div>
          <div className="col-span-4"><F label="Parameters (JSON object, metadata — không được tính toán)"><input className={inp} value={d.parameters} onChange={(e) => setD({ ...d, parameters: e.target.value })} placeholder='{"note": "..."}' /></F></div>
          <div className="col-span-4 text-right"><button disabled={!d.rule_code.trim()} className={primary} data-testid="roadmap-rule-save" onClick={() => void create()}>+ Tạo rule Draft</button></div>
        </div>
      )}
    </Modal>
  );
}
