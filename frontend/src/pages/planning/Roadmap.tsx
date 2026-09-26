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
  cost_families: string[]; cost_approvable_source_kinds: Record<string, string[]>; cost_blocked_source_kinds: string[]; machine_price_bases: string[]; asset_kinds: string[]; asset_subject_types: string[];
  exec_approvable_source_kinds: string[]; exec_blocked_source_kinds: string[]; adapters: { adapter_code: string; adapter_version: string; proposal_type: string; needs_machine_type: boolean; productivity_units: string[]; description: string }[];
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
  calculation: Record<string, unknown> | null; capacity_impact: CapacityImpact | null;
}
interface CapacityImpact { requirement_basis: string; capacity_unit: string; period_type: string; gap_output: number; baseline_capacity: number | null; proposed_increment: number; resulting_capacity: number | null; remaining_gap: number; completeness: string; note: string }
interface ExecRule {
  id: number; rule_code: string; rule_version: number; title: string; adapter_code: string; adapter_version: string; proposal_type: string; scope_type: string; scope_value: string; period_type: string;
  machine_type_code: string | null; productivity_value: number; productivity_unit: string; owner: string; source_kind: string; source_ref: string; effective_from: string | null; effective_to: string | null;
  assumptions: string; sample_input: Record<string, unknown>; sample_expected: Record<string, unknown>; status: string; executable: boolean; reviewed_by: string; approved_by: string;
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
  RETIRED: "bg-slate-500/20 text-slate-400", UNDER_REVIEW: "pg-adv", COUNTED: "pg-ok", UNRESOLVED: "pg-adv",
  PRICED: "pg-ok", UNPRICED: "pg-adv", COMPLETE_PRICING: "pg-ok", PARTIAL_PRICING: "pg-adv",
  NOT_COVERED: "bg-slate-500/20 text-slate-500", PARTIALLY_COVERED: "pg-adv", COVERED: "pg-ok", OVER_COVERED: "pg-known", NOT_COMBINABLE: "pg-adv",
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
  const [execOpen, setExecOpen] = useState(false);
  const [costOpen, setCostOpen] = useState(false);
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
        <button onClick={() => setCostOpen(true)} className={btn} data-testid="roadmap-cost-open">Cost Evidence</button>
        <button onClick={() => setExecOpen(true)} className={btn} data-testid="roadmap-exec-open">Rule thực thi</button>
        <button onClick={() => setRulesOpen(true)} className={btn} data-testid="roadmap-rules-open">Rule registry (metadata)</button>
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
      {costOpen && opts && <CostEvidenceModal opts={opts} perm={perm} onClose={() => setCostOpen(false)} setMsg={setMsg} />}
      {execOpen && opts && <ExecRulesModal opts={opts} perm={perm} onClose={() => setExecOpen(false)} setMsg={setMsg} />}
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
      {versionId !== null ? <VersionPanel key={versionId} versionId={versionId} opts={opts} perm={s.status === "ARCHIVED" ? { ...perm, manage: false, run: false, archived: true } : perm} onChanged={() => { void load(); onChanged(); }} setMsg={setMsg} /> : <p className="text-sm text-slate-400">Scenario chưa có version. Tạo version để nhập milestone/target.</p>}
    </div>
  );
}

function VersionPanel({ versionId, opts, perm, onChanged, setMsg }: { versionId: number; opts: Options; perm: { manage: boolean; run: boolean; approve: boolean; archived?: boolean }; onChanged: () => void; setMsg: (m: Msg) => void }) {
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

function RunResult({ runId, perm, setMsg }: { runId: number; perm: { manage: boolean; approve?: boolean; archived?: boolean }; setMsg: (m: Msg) => void }) {
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
            <td className="px-3 text-right">{p.quantity === null ? <span className="text-slate-400">N/A</span> : `+${num(p.quantity)} ${p.unit}`}{p.quantity !== null && <div className="text-[10px] text-slate-400">tăng thêm để bù gap (không phải tổng nhu cầu)</div>}
              {p.capacity_impact && <div className="mt-1 text-[10px] text-slate-500" data-testid={`roadmap-capacity-impact-${p.id}`}>Capacity impact ({p.capacity_impact.completeness}): +{num(p.capacity_impact.proposed_increment)} {p.capacity_impact.capacity_unit}/{p.capacity_impact.period_type}; còn lại {num(p.capacity_impact.remaining_gap)}{p.capacity_impact.remaining_gap < 0 ? " (vượt gap do làm tròn)" : ""}; baseline/resulting capacity: chưa xác định</div>}</td><td className="px-3 font-mono text-[11px]">{p.calculation_rule_version}</td>
            <td className="px-3">{p.rationale}{p.missing_inputs.length > 0 && <ul className="list-disc pl-4 text-[11px] text-red-600">{p.missing_inputs.map((m) => <li key={m}>{m}</li>)}</ul>}{p.decision_reason && <div className="text-[11px] text-slate-500">Quyết định: {p.decision_reason}</div>}</td>
            <td className="whitespace-nowrap px-3 text-right">
              <button onClick={() => setDrawer({ title: `Evidence — ${p.proposal_type}`, data: { input_snapshot: p.input_snapshot, evidence_refs: p.evidence_refs, missing_inputs: p.missing_inputs, calculation_rule_version: p.calculation_rule_version } })} className="text-brand hover:underline">Evidence</button>
              {perm.manage && <><button onClick={() => void decide(p, "SELECTED")} disabled={p.decision_status === "SELECTED"} className="ml-2 text-green-700 hover:underline disabled:opacity-40" data-testid={`roadmap-select-${p.id}`}>Chọn</button>
                <button onClick={() => void decide(p, "REJECTED")} disabled={p.decision_status === "REJECTED"} className="ml-2 text-red-600 hover:underline disabled:opacity-40">Loại</button></>}
            </td>
          </tr>
        ))}</tbody></table></div>
      <ActionPlanPanel runId={r.id} proposals={r.proposals} perm={{ manage: perm.manage, approve: !!perm.approve, archived: !!perm.archived }} setMsg={setMsg} />
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
      <p className="text-xs text-slate-500">Task 5 chỉ lưu <b>metadata, evidence, version và trạng thái duyệt</b> của rule. Rule KHÔNG được thực thi: chưa có công thức/adapter tính toán nào được business duyệt, nên proposal Labor/Machine chỉ tính khi có <b>Rule thực thi</b> riêng (nút "Rule thực thi") được duyệt; rule metadata APPROVED không tự tính. Rule APPROVED bất biến — sửa = version mới. Không có rule nào được cấu hình sẵn.</p>
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


const EXEC_EMPTY = { rule_code: "", adapter_code: "", scope_type: "TOTAL", scope_value: "", period_type: "MONTH", machine_type_code: "", productivity_value: "", owner: "", source_kind: "", source_ref: "", effective_from: "", effective_to: "", assumptions: "", s_gap: "", s_avail: "", s_add: "", s_inc: "", s_rem: "" };

/** Task 6 (Issue #13): executable rule — adapter allowlist (LABOR/MACHINE_GAP_REQUIREMENT_V1), productivity do business khai báo, four-eyes. */
function ExecRulesModal({ opts, perm, onClose, setMsg }: { opts: Options; perm: { manage: boolean; approve: boolean }; onClose: () => void; setMsg: (m: Msg) => void }) {
  const [rules, setRules] = useState<ExecRule[]>([]);
  const [d, setD] = useState({ ...EXEC_EMPTY, adapter_code: opts.adapters[0]?.adapter_code ?? "" });
  const [drawer, setDrawer] = useState<{ title: string; data: unknown } | null>(null);
  const load = useCallback(async () => setRules((await api.get<ExecRule[]>(`${RES}/executable-rules`)).data), []);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const adapter = opts.adapters.find((a) => a.adapter_code === d.adapter_code);
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); setMsg({ ok: true, text: ok }); await load(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  const isMachine = !!adapter?.needs_machine_type;
  const create = async () => {
    const unit = adapter?.productivity_units.find((u) => u.endsWith(`/${d.period_type}`)) ?? "";
    const prod = Number(d.productivity_value);
    const sample_input: Record<string, unknown> = { gap_output: Number(d.s_gap), gap_unit: "sp", period_type: d.period_type, productivity_unit: unit, [isMachine ? "productivity_per_machine" : "productivity_per_worker"]: prod, [isMachine ? "available_machines" : "available_labor"]: Number(d.s_avail) };
    if (isMachine) sample_input.machine_type_code = d.machine_type_code;
    const sample_expected = { [isMachine ? "required_incremental_machines" : "required_incremental_labor"]: Number(d.s_add), [isMachine ? "additional_machines" : "additional_labor"]: Number(d.s_add), proposed_increment: Number(d.s_inc), remaining_gap_after_proposal: Number(d.s_rem) };
    await act(async () => {
      await api.post(`${RES}/executable-rules`, {
        rule_code: d.rule_code, adapter_code: d.adapter_code, scope_type: d.scope_type, scope_value: d.scope_value, period_type: d.period_type, machine_type_code: isMachine ? d.machine_type_code : undefined,
        productivity_value: prod, productivity_unit: unit, owner: d.owner, source_kind: d.source_kind, source_ref: d.source_ref, effective_from: d.effective_from || undefined, effective_to: d.effective_to || undefined,
        assumptions: d.assumptions, sample_input, sample_expected,
      });
      setD({ ...EXEC_EMPTY, adapter_code: d.adapter_code });
    }, "Đã tạo rule thực thi (Draft).");
  };
  const showHistory = async (r: ExecRule) => { try { setDrawer({ title: `Lịch sử — ${r.rule_code}@v${r.rule_version}`, data: (await api.get(`${RES}/executable-rules/${r.id}/history`)).data }); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  const verify = async (r: ExecRule) => { try { setDrawer({ title: `Sample calculation — ${r.rule_code}@v${r.rule_version}`, data: (await api.post(`${RES}/executable-rules/${r.id}/verify-sample`)).data }); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  return (
    <Modal title="Rule thực thi — productivity do business khai báo (adapter allowlist)" onClose={onClose} wide>
      <p className="text-xs text-slate-500">Chỉ có 2 adapter: <b>LABOR_GAP_REQUIREMENT_V1</b> và <b>MACHINE_GAP_REQUIREMENT_V1</b>. Công thức: <span className="font-mono">tăng thêm = CEIL(gap_output / productivity)</span> — <b>incremental gap</b>, không phải tổng nhu cầu; available labor/machine chỉ là context, không bị trừ. Productivity phải đúng period target (MONTH/YEAR, không quy đổi) và do business khai báo kèm nguồn (IE_APPROVED_STUDY, TIME_MOTION_STUDY, APPROVED_CAPACITY_STUDY, CONTROLLED_PRODUCTION_TRIAL); ESTIMATE/DEFAULT/CLAIMED/BROCHURE/PLACEHOLDER/UNVERIFIED không duyệt được. Quy trình DRAFT → UNDER_REVIEW → APPROVED, người duyệt phải khác người review. Chưa có rule nào được cấu hình sẵn: khi chưa có rule APPROVED, proposal Labor/Machine là NEEDS_INPUT.</p>
      <div className="mt-3 max-h-80 overflow-y-auto rounded-xl border border-slate-200">
        <table className="w-full text-xs" data-testid="roadmap-exec-table"><thead><tr><th className={th}>Rule</th><th className={th}>Adapter</th><th className={th}>Scope / kỳ</th><th className={th}>Productivity</th><th className={th}>Hiệu lực</th><th className={th}>Nguồn</th><th className={th}>Trạng thái</th><th /></tr></thead>
          <tbody>{rules.map((r) => (
            <tr key={r.id} className="border-t border-slate-100 align-top" data-testid={`roadmap-exec-row-${r.id}`}>
              <td className="px-3 py-1.5 font-mono">{r.rule_code}@v{r.rule_version}<div className="text-[10px] text-slate-400">{r.owner || "chưa có owner"}</div></td>
              <td className="px-3 font-mono text-[11px]">{r.adapter_code}{r.machine_type_code ? ` (${r.machine_type_code})` : ""}</td>
              <td className="px-3">{r.scope_type}{r.scope_value ? `/${r.scope_value}` : ""} · {r.period_type}</td>
              <td className="px-3">{r.productivity_value} <span className="text-[10px] text-slate-400">{r.productivity_unit}</span></td>
              <td className="px-3">{r.effective_from ?? "—"} → {r.effective_to ?? "mở"}</td>
              <td className="px-3">{r.source_kind || "—"}<div className="text-[10px] text-slate-400">{r.source_ref}</div></td>
              <td className="px-3"><Chip s={r.status} />{r.reviewed_by && <div className="text-[10px] text-slate-400">review: {r.reviewed_by}</div>}{r.approved_by && <div className="text-[10px] text-slate-400">duyệt: {r.approved_by}</div>}</td>
              <td className="whitespace-nowrap px-3 text-right">
                <button onClick={() => void verify(r)} className="text-brand hover:underline">Sample</button>
                <button onClick={() => void showHistory(r)} className="ml-2 text-brand hover:underline">Lịch sử</button>
                {perm.manage && r.status === "DRAFT" && <button onClick={() => void act(() => api.post(`${RES}/executable-rules/${r.id}/submit-review`), "Đã chuyển UNDER_REVIEW (bạn là reviewer).")} className="ml-2 text-amber-700 hover:underline" data-testid={`roadmap-exec-review-${r.id}`}>Gửi review</button>}
                {perm.approve && r.status === "UNDER_REVIEW" && <button onClick={() => void act(() => api.post(`${RES}/executable-rules/${r.id}/approve`), "Đã duyệt rule thực thi.")} className="ml-2 text-green-700 hover:underline" data-testid={`roadmap-exec-approve-${r.id}`}>Duyệt</button>}
                {perm.approve && r.status === "APPROVED" && <button onClick={() => { const reason = window.prompt("Lý do retire rule? (bắt buộc)") ?? ""; if (reason.trim()) void act(() => api.post(`${RES}/executable-rules/${r.id}/retire`, { reason }), "Đã retire rule."); }} className="ml-2 text-red-600 hover:underline">Retire</button>}
                {perm.manage && (r.status === "APPROVED" || r.status === "RETIRED") && <button onClick={() => void act(() => api.post(`${RES}/executable-rules/${r.id}/new-version`), "Đã tạo version mới (Draft).")} className="ml-2 text-brand hover:underline">Version mới</button>}
              </td></tr>
          ))}{rules.length === 0 && <tr><td colSpan={8} className="py-4 text-center text-slate-400">Chưa có rule thực thi nào (đúng: production không seed productivity).</td></tr>}</tbody></table>
      </div>
      {perm.manage && (
        <div className="mt-3 grid grid-cols-4 gap-2 rounded-xl border border-slate-200 p-3">
          <F label="Mã rule"><input className={inp} value={d.rule_code} onChange={(e) => setD({ ...d, rule_code: e.target.value })} data-testid="roadmap-exec-code" /></F>
          <F label="Adapter"><select className={inp} value={d.adapter_code} onChange={(e) => setD({ ...d, adapter_code: e.target.value })}>{opts.adapters.map((a) => <option key={a.adapter_code} value={a.adapter_code}>{a.adapter_code}</option>)}</select></F>
          <F label="Scope"><select className={inp} value={d.scope_type} onChange={(e) => setD({ ...d, scope_type: e.target.value })}>{opts.scope_types.map((t) => <option key={t}>{t}</option>)}</select></F>
          <F label="Factory (khi FACTORY)"><input className={inp} value={d.scope_value} disabled={d.scope_type !== "FACTORY"} onChange={(e) => setD({ ...d, scope_value: e.target.value })} /></F>
          <F label="Kỳ (phải khớp kỳ target)"><select className={inp} value={d.period_type} onChange={(e) => setD({ ...d, period_type: e.target.value })}>{opts.period_types.map((t) => <option key={t}>{t}</option>)}</select></F>
          <F label={`Productivity (${adapter?.productivity_units.find((u) => u.endsWith(`/${d.period_type}`)) ?? "sp/…"})`}><input className={inp} type="number" min="0" value={d.productivity_value} onChange={(e) => setD({ ...d, productivity_value: e.target.value })} data-testid="roadmap-exec-prod" /></F>
          <F label="Loại máy (Machine adapter)"><input className={inp} value={d.machine_type_code} disabled={!isMachine} onChange={(e) => setD({ ...d, machine_type_code: e.target.value })} /></F>
          <F label="Owner"><input className={inp} value={d.owner} onChange={(e) => setD({ ...d, owner: e.target.value })} /></F>
          <F label="Loại nguồn"><select className={inp} value={d.source_kind} onChange={(e) => setD({ ...d, source_kind: e.target.value })}><option value="" />{[...opts.exec_approvable_source_kinds, ...opts.exec_blocked_source_kinds].map((k) => <option key={k} value={k}>{k}{opts.exec_blocked_source_kinds.includes(k) ? " (không duyệt được)" : ""}</option>)}</select></F>
          <div className="col-span-3"><F label="Source ref (tài liệu/mã nghiên cứu)"><input className={inp} value={d.source_ref} onChange={(e) => setD({ ...d, source_ref: e.target.value })} /></F></div>
          <F label="Hiệu lực từ"><input className={inp} type="date" value={d.effective_from} onChange={(e) => setD({ ...d, effective_from: e.target.value })} /></F>
          <F label="Hiệu lực đến (tùy chọn)"><input className={inp} type="date" value={d.effective_to} onChange={(e) => setD({ ...d, effective_to: e.target.value })} /></F>
          <div className="col-span-2"><F label="Assumptions"><input className={inp} value={d.assumptions} onChange={(e) => setD({ ...d, assumptions: e.target.value })} /></F></div>
          <div className="col-span-4 text-[11px] font-semibold text-slate-500">Sample calculation (business tự tính tay; adapter chạy lại và phải khớp mới được review/duyệt)</div>
          <F label="Gap mẫu (sp)"><input className={inp} type="number" value={d.s_gap} onChange={(e) => setD({ ...d, s_gap: e.target.value })} /></F>
          <F label={isMachine ? "Available machines mẫu" : "Available labor mẫu"}><input className={inp} type="number" value={d.s_avail} onChange={(e) => setD({ ...d, s_avail: e.target.value })} /></F>
          <F label={isMachine ? "Kỳ vọng: máy tăng thêm" : "Kỳ vọng: lao động tăng thêm"}><input className={inp} type="number" value={d.s_add} onChange={(e) => setD({ ...d, s_add: e.target.value })} /></F>
          <F label="Kỳ vọng: proposed_increment (sp)"><input className={inp} type="number" value={d.s_inc} onChange={(e) => setD({ ...d, s_inc: e.target.value })} /></F>
          <F label="Kỳ vọng: remaining_gap (sp, giữ dấu)"><input className={inp} type="number" value={d.s_rem} onChange={(e) => setD({ ...d, s_rem: e.target.value })} /></F>
          <div className="col-span-3 text-right"><button disabled={!d.rule_code.trim() || !d.productivity_value} className={primary} data-testid="roadmap-exec-save" onClick={() => void create()}>+ Tạo rule Draft</button></div>
        </div>
      )}
      {drawer && <Modal title={drawer.title} onClose={() => setDrawer(null)} wide><J v={drawer.data} /></Modal>}
    </Modal>
  );
}


interface ApVersionRow { id: number; plan_id: number; action_plan_code: string; name: string; version_no: number; status: string }
interface ApPlan { id: number; action_plan_code: string; name: string; versions: ApVersionRow[] }
interface ApItem {
  id: number; proposal_id: number; proposal_type: string; source_milestone_code: string; planned_effective_date: string; selected_quantity: number | null; planned_increment: number | null; unit: string;
  impact_persistence: string; inclusion_status: string; notes: string; current_proposal_decision_changed: boolean; snapshot: unknown;
}
interface ApCov { status: string; planned_increment: number; remaining_gap: number }
interface ApTarget {
  target_result_id: number; milestone_code: string; period_label: string; baseline_value: number | null; effective_target: number | null; original_gap: number; unit: string;
  coverage_by_proposal_type: Record<string, ApCov>; mixed_resource_types: boolean; overall_combined_status: string; planned_increment: number | null; remaining_gap_after_plan: number | null; has_unresolved_actions: boolean;
}
interface ApDetail extends ApVersionRow {
  editable: boolean; coverage_frozen: boolean; reviewed_by: string; approved_by: string; source_run_fingerprint: string; items: ApItem[]; coverage: { targets: ApTarget[]; unresolved_items: { item_id: number; proposal_type: string; source_milestone_code: string }[] };
}

/** Task 7 (Issue #15): Action Plan theo milestone — user chọn thủ công; coverage OUTPUT_QTY tách theo proposal_type (không cộng chéo labor+machine). Không optimizer/ranking, không thực thi mua/tuyển. */
function ActionPlanPanel({ runId, proposals, perm, setMsg }: { runId: number; proposals: Proposal[]; perm: { manage: boolean; approve: boolean; archived?: boolean }; setMsg: (m: Msg) => void }) {
  const [plans, setPlans] = useState<ApPlan[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [det, setDet] = useState<ApDetail | null>(null);
  const [drawer, setDrawer] = useState<{ title: string; data: unknown } | null>(null);
  const [f, setF] = useState({ proposal_id: "", date: "", qty: "", unresolved: false, notes: "" });
  const [name, setName] = useState("");
  const loadPlans = useCallback(async () => setPlans((await api.get<ApPlan[]>(`${RES}/action-plans?source_run_id=${runId}`)).data), [runId]);
  const loadDet = useCallback(async (id: number) => setDet((await api.get<ApDetail>(`${RES}/action-plan-versions/${id}`)).data), []);
  useEffect(() => { loadPlans().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [loadPlans, setMsg]);
  useEffect(() => { if (sel !== null) loadDet(sel).catch((e) => setMsg({ ok: false, text: errorMessage(e) })); else setDet(null); }, [sel, loadDet, setMsg]);
  const act = async (fn: () => Promise<unknown>, ok: string, then?: () => Promise<void>) => { try { await fn(); setMsg({ ok: true, text: ok }); await loadPlans(); if (sel !== null) await loadDet(sel); if (then) await then(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  const create = async () => { try { const v = (await api.post<ApDetail>(`${RES}/runs/${runId}/action-plans`, { name })).data; setName(""); await loadPlans(); setSel(v.id); setMsg({ ok: true, text: `Đã tạo ${v.action_plan_code} v1 (Draft).` }); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  const pickable = proposals.filter((p) => p.calc_status !== "NOT_APPLICABLE" && p.decision_status !== "REJECTED");
  const chosen = pickable.find((p) => String(p.id) === f.proposal_id);
  const addItem = () => act(async () => {
    await api.post(`${RES}/action-plan-versions/${det!.id}/items`, { proposal_id: Number(f.proposal_id), planned_effective_date: f.date, selected_quantity: f.qty && !f.unresolved ? Number(f.qty) : undefined, as_unresolved: f.unresolved || undefined, notes: f.notes });
    setF({ ...f, qty: "", notes: "" });
  }, "Đã thêm item.");
  const allVersions = plans.flatMap((p) => p.versions);
  const compare = async (otherId: number) => { try { setDrawer({ title: `So sánh v${det?.version_no} ↔ #${otherId} (không xếp hạng)`, data: (await api.get(`${RES}/action-plan-compare/${det!.id}/${otherId}`)).data }); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 p-3" data-testid="roadmap-action-plan">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-bold">Action Plan (chọn thủ công, không tự chọn/xếp hạng)</h4><span className="flex-1" />
        {perm.manage && <><input className={`${inp} !w-48`} placeholder="Tên Action Plan" value={name} onChange={(e) => setName(e.target.value)} /><button className={primary} onClick={() => void create()} data-testid="roadmap-ap-create">+ Tạo Action Plan từ Run</button></>}
      </div>
      <div className="flex flex-wrap gap-2 text-xs" data-testid="roadmap-ap-list">
        {plans.length === 0 && <span className="text-slate-400">Chưa có Action Plan cho Run này.</span>}
        {allVersions.map((v) => <button key={v.id} onClick={() => setSel(v.id)} className={`rounded-full border px-3 py-1 ${sel === v.id ? "border-brand bg-brand/10" : "border-slate-300"}`}>{v.action_plan_code} v{v.version_no} <Chip s={v.status} /></button>)}
      </div>
      {det && (
        <div className="space-y-3" data-testid="roadmap-ap-detail">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <b>{det.action_plan_code} v{det.version_no}</b><Chip s={det.status} /><span className="text-slate-400">{det.reviewed_by && `review: ${det.reviewed_by}`} {det.approved_by && `· duyệt: ${det.approved_by}`} · coverage {det.coverage_frozen ? "đã đóng băng" : "preview (tính từ snapshot)"}</span><span className="flex-1" />
            {perm.manage && det.status === "DRAFT" && <button className={btn} onClick={() => void act(() => api.post(`${RES}/action-plan-versions/${det.id}/submit-review`), "Đã chuyển UNDER_REVIEW (bạn là reviewer).")} data-testid="roadmap-ap-review">Gửi review</button>}
            {perm.approve && !perm.archived && det.status === "UNDER_REVIEW" && <button className={primary} onClick={() => void act(() => api.post(`${RES}/action-plan-versions/${det.id}/approve`), "Đã duyệt Action Plan (không thực thi mua/tuyển).")} data-testid="roadmap-ap-approve">Duyệt</button>}
            {perm.approve && det.status === "APPROVED" && <button className={btn} onClick={() => { const reason = window.prompt("Lý do archive? (bắt buộc)") ?? ""; if (reason.trim()) void act(() => api.post(`${RES}/action-plan-versions/${det.id}/archive`, { reason }), "Đã archive."); }}>Archive</button>}
            {perm.manage && (det.status === "APPROVED" || det.status === "ARCHIVED") && <button className={btn} onClick={() => void act(async () => { const v = (await api.post<ApDetail>(`${RES}/action-plan-versions/${det.id}/new-version`)).data; setSel(v.id); }, "Đã tạo version mới (Draft, giữ nguyên source run).")}>Version mới</button>}
            <select className={`${inp} !w-44`} value="" onChange={(e) => { if (e.target.value) void compare(Number(e.target.value)); }}><option value="">So sánh với…</option>{allVersions.filter((v) => v.id !== det.id).map((v) => <option key={v.id} value={v.id}>{v.action_plan_code} v{v.version_no}</option>)}</select>
          </div>
          {det.editable && perm.manage && (
            <div className="grid grid-cols-5 gap-2 rounded-lg border border-slate-200 p-2">
              <div className="col-span-2"><F label="Proposal (chỉ CALCULATED/NEEDS_INPUT, không REJECTED)"><select className={inp} value={f.proposal_id} onChange={(e) => setF({ ...f, proposal_id: e.target.value })} data-testid="roadmap-ap-proposal"><option value="" />{pickable.map((p) => <option key={p.id} value={p.id}>{p.milestone_code} · {PTYPE_LABEL[p.proposal_type] ?? p.proposal_type} · {p.calculation_rule_version} · {p.calc_status}{p.quantity !== null ? ` (${num(p.quantity)} ${p.unit})` : ""}</option>)}</select></F></div>
              <F label="Ngày hiệu lực"><input className={inp} type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} data-testid="roadmap-ap-date" /></F>
              <F label={`Số lượng (nguyên${chosen?.quantity ? `, 1..${chosen.quantity}` : ""}; trống = full)`}><input className={inp} type="number" min="1" step="1" value={f.qty} disabled={f.unresolved} onChange={(e) => setF({ ...f, qty: e.target.value })} data-testid="roadmap-ap-qty" /></F>
              <label className="flex items-end gap-1 pb-1 text-xs text-slate-500"><input type="checkbox" checked={f.unresolved} onChange={(e) => setF({ ...f, unresolved: e.target.checked })} />Chỉ theo dõi (UNRESOLVED)</label>
              <div className="col-span-4"><F label="Ghi chú"><input className={inp} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></F></div>
              <div className="flex items-end justify-end"><button className={primary} disabled={!f.proposal_id || !f.date} onClick={() => void addItem()} data-testid="roadmap-ap-add">+ Thêm item</button></div>
              <p className="col-span-5 text-[11px] text-slate-500">Labor/Machine CALCULATED được chọn từng phần (số nguyên) — planned_increment = số lượng × productivity trong snapshot của proposal, persistence cố định PERSISTENT. Các loại khác chỉ là UNRESOLVED (không tính coverage). Không chọn nhiều rule cùng loại cho cùng target (là phương án thay thế).</p>
            </div>
          )}
          <div className="overflow-x-auto"><table className="w-full text-xs" data-testid="roadmap-ap-items">
            <thead><tr><th className={th}>Proposal</th><th className={th}>Milestone nguồn</th><th className={th}>Hiệu lực</th><th className={`${th} text-right`}>Số lượng</th><th className={`${th} text-right`}>Planned increment</th><th className={th}>Trạng thái</th><th /></tr></thead>
            <tbody>{det.items.map((i) => (
              <tr key={i.id} className="border-t border-slate-100 align-top">
                <td className="px-3 py-1.5">{PTYPE_LABEL[i.proposal_type] ?? i.proposal_type} <span className="font-mono text-[10px] text-slate-400">#{i.proposal_id}</span>{i.current_proposal_decision_changed && <div className="text-[10px] text-amber-700">quyết định của proposal đã đổi sau khi chọn (coverage dùng snapshot)</div>}</td>
                <td className="px-3 font-mono">{i.source_milestone_code}</td><td className="px-3">{i.planned_effective_date}</td>
                <td className="px-3 text-right">{i.selected_quantity === null ? "—" : `${i.selected_quantity} ${i.unit}`}</td>
                <td className="px-3 text-right">{i.planned_increment === null ? <span className="text-slate-400">không tính</span> : `${num(i.planned_increment)} sp`}</td>
                <td className="px-3"><Chip s={i.inclusion_status} /><div className="text-[10px] text-slate-400">{i.impact_persistence}</div></td>
                <td className="whitespace-nowrap px-3 text-right"><button className="text-brand hover:underline" onClick={() => setDrawer({ title: `Snapshot item #${i.id}`, data: i.snapshot })}>Evidence</button>
                  {det.editable && perm.manage && <button className="ml-2 text-red-600 hover:underline" onClick={() => void act(() => api.delete(`${RES}/action-plan-items/${i.id}`), "Đã xóa item.")}>Xóa</button>}</td>
              </tr>
            ))}{det.items.length === 0 && <tr><td colSpan={7} className="py-3 text-center text-slate-400">Chưa chọn item nào.</td></tr>}</tbody></table></div>
          <h5 className="text-xs font-bold">Milestone coverage — OUTPUT_QTY (tách theo loại nguồn lực; LABOR + MACHINE không cộng chéo)</h5>
          <div className="overflow-x-auto"><table className="w-full text-xs" data-testid="roadmap-ap-coverage">
            <thead><tr><th className={th}>Milestone / kỳ</th><th className={`${th} text-right`}>Baseline</th><th className={`${th} text-right`}>Target</th><th className={`${th} text-right`}>Original gap</th><th className={th}>Planned / Remaining theo loại</th><th className={th}>Coverage</th></tr></thead>
            <tbody>{det.coverage.targets.map((t) => (
              <tr key={t.target_result_id} className="border-t border-slate-100 align-top" data-testid={`roadmap-ap-cov-${t.milestone_code}`}>
                <td className="px-3 py-1.5 font-mono">{t.milestone_code} · {t.period_label}</td>
                <td className="px-3 text-right">{t.baseline_value === null ? "—" : num(t.baseline_value)}</td><td className="px-3 text-right">{t.effective_target === null ? "—" : num(t.effective_target)}</td><td className="px-3 text-right font-semibold">{num(t.original_gap)}</td>
                <td className="px-3">{Object.keys(t.coverage_by_proposal_type).length === 0 ? <span className="text-slate-400">chưa có item được tính</span> : Object.entries(t.coverage_by_proposal_type).map(([k, c]) => <div key={k}>{PTYPE_LABEL[k] ?? k}: +{num(c.planned_increment)} · còn lại {num(c.remaining_gap)}{c.remaining_gap < 0 ? " (vượt)" : ""} <Chip s={c.status} /></div>)}</td>
                <td className="px-3">{t.mixed_resource_types ? <><Chip s="NOT_COMBINABLE" /><div className="text-[10px] text-amber-700">MIXED_RESOURCE_TYPES — không có tổng remaining gap</div></> : <Chip s={t.overall_combined_status} />}{t.has_unresolved_actions && <div className="text-[10px] text-amber-700">có action chưa giải quyết (UNRESOLVED)</div>}</td>
              </tr>
            ))}{det.coverage.targets.length === 0 && <tr><td colSpan={6} className="py-3 text-center text-slate-400">Run không có target OUTPUT_QTY với gap &gt; 0.</td></tr>}</tbody></table></div>
          {det.status === "APPROVED" && <DecisionPackagePanel apVersionId={det.id} items={det.items} perm={perm} setMsg={setMsg} />}
          {det.coverage.unresolved_items.length > 0 && <p className="text-xs text-amber-700" data-testid="roadmap-ap-unresolved">Unresolved (không tính coverage): {det.coverage.unresolved_items.map((u) => `${PTYPE_LABEL[u.proposal_type] ?? u.proposal_type} @${u.source_milestone_code}`).join(", ")}</p>}
        </div>
      )}
      {drawer && <Modal title={drawer.title} onClose={() => setDrawer(null)} wide><J v={drawer.data} /></Modal>}
    </div>
  );
}


interface CostEv {
  id: number; evidence_code: string; evidence_version: number; cost_family: string; machine_type_code: string | null; machine_model_id: number | null; future_candidate_id: number | null;
  scope_type: string; scope_value: string; cost_period: string; amount: string; currency: string; price_basis: string; vendor: string; source_kind: string; source_ref: string;
  effective_from: string | null; effective_to: string | null; quote_valid_until: string | null; status: string; reviewed_by: string; approved_by: string;
}
const EV_EMPTY = { evidence_code: "", cost_family: "MACHINE_UNIT_PRICE", machine_type_code: "", machine_model_id: "", future_candidate_id: "", scope_type: "TOTAL", scope_value: "", cost_period: "MONTH", amount: "", currency: "USD", price_basis: "", vendor: "", source_kind: "", source_ref: "", evidence_date: "", quote_valid_until: "", effective_from: "", effective_to: "" };

/** Task 8 (Issue #17): cost evidence versioned/effective-dated — machine unit price / labor cost per worker per period. Không seed; APPROVED mới được dùng; four-eyes. */
function CostEvidenceModal({ opts, perm, onClose, setMsg }: { opts: Options; perm: { manage: boolean; approve: boolean }; onClose: () => void; setMsg: (m: Msg) => void }) {
  const [rows, setRows] = useState<CostEv[]>([]);
  const [d, setD] = useState(EV_EMPTY);
  const [asset, setAsset] = useState({ subject_type: "MACHINE_TYPE", subject_ref: "", asset_kind: "IMAGE", uri: "", asset_ref: "" });
  const load = useCallback(async () => setRows((await api.get<CostEv[]>(`${RES}/cost-evidence`)).data), []);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); setMsg({ ok: true, text: ok }); await load(); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  const machine = d.cost_family === "MACHINE_UNIT_PRICE";
  const kinds = [...(opts.cost_approvable_source_kinds[d.cost_family] ?? []), ...opts.cost_blocked_source_kinds];
  const create = () => act(async () => {
    const n = (v: string) => (v ? Number(v) : undefined);
    await api.post(`${RES}/cost-evidence`, {
      evidence_code: d.evidence_code, cost_family: d.cost_family, amount: d.amount, currency: d.currency, source_kind: d.source_kind, source_ref: d.source_ref, vendor: d.vendor,
      evidence_date: d.evidence_date || undefined, quote_valid_until: d.quote_valid_until || undefined, effective_from: d.effective_from || undefined, effective_to: d.effective_to || undefined,
      ...(machine ? { machine_type_code: d.machine_type_code, machine_model_id: n(d.machine_model_id), future_candidate_id: n(d.future_candidate_id), price_basis: d.price_basis || undefined }
        : { scope_type: d.scope_type, scope_value: d.scope_value, cost_period: d.cost_period }),
    });
    setD({ ...EV_EMPTY, cost_family: d.cost_family });
  }, "Đã tạo cost evidence (Draft).");
  const addAsset = () => act(async () => { await api.post(`${RES}/asset-refs`, { ...asset, uri: asset.uri || undefined, asset_ref: asset.asset_ref || undefined }); setAsset({ ...asset, uri: "", asset_ref: "" }); }, "Đã thêm asset ref (chỉ tham chiếu).");
  return (
    <Modal title="Cost Evidence — giá máy / chi phí lao động (versioned, evidence-only)" onClose={onClose} wide>
      <p className="text-xs text-slate-500">Cost evidence là <b>bằng chứng có version và hiệu lực</b>, không phải trường giá sống. Chỉ evidence <b>APPROVED</b> (nguồn thuộc allowlist theo loại, reviewer ≠ approver) mới được gắn vào Decision Package. Số tiền lưu Decimal chính xác; không quy đổi tiền tệ/kỳ; machine chỉ tính <span className="font-mono">số lượng × đơn giá</span> (price_basis chỉ mô tả phạm vi thương mại — không cộng thuế/vận chuyển/lắp đặt). Chưa có evidence nào được cấu hình sẵn.</p>
      <div className="mt-3 max-h-72 overflow-y-auto rounded-xl border border-slate-200">
        <table className="w-full text-xs" data-testid="roadmap-cost-table"><thead><tr><th className={th}>Evidence</th><th className={th}>Loại / đối tượng</th><th className={`${th} text-right`}>Đơn giá</th><th className={th}>Hiệu lực</th><th className={th}>Nguồn</th><th className={th}>Trạng thái</th><th /></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id} className="border-t border-slate-100 align-top">
              <td className="px-3 py-1.5 font-mono">{r.evidence_code}@v{r.evidence_version}</td>
              <td className="px-3">{r.cost_family === "MACHINE_UNIT_PRICE" ? `Máy ${r.machine_type_code}${r.machine_model_id ? ` · model#${r.machine_model_id}` : ""}${r.future_candidate_id ? ` · cand#${r.future_candidate_id}` : ""}` : `Lao động ${r.scope_type}${r.scope_value ? `/${r.scope_value}` : ""} · /${r.cost_period}`}<div className="text-[10px] text-slate-400">{r.price_basis}</div></td>
              <td className="px-3 text-right font-mono">{r.amount} {r.currency}</td>
              <td className="px-3">{r.effective_from ?? "—"} → {r.effective_to ?? "mở"}{r.quote_valid_until && <div className="text-[10px] text-slate-400">quote đến {r.quote_valid_until}</div>}</td>
              <td className="px-3">{r.source_kind}<div className="text-[10px] text-slate-400">{r.vendor} {r.source_ref}</div></td>
              <td className="px-3"><Chip s={r.status} />{r.reviewed_by && <div className="text-[10px] text-slate-400">review: {r.reviewed_by}</div>}{r.approved_by && <div className="text-[10px] text-slate-400">duyệt: {r.approved_by}</div>}</td>
              <td className="whitespace-nowrap px-3 text-right">
                {perm.manage && r.status === "DRAFT" && <button className="text-amber-700 hover:underline" onClick={() => void act(() => api.post(`${RES}/cost-evidence/${r.id}/submit-review`), "Đã chuyển UNDER_REVIEW (bạn là reviewer).")}>Gửi review</button>}
                {perm.approve && r.status === "UNDER_REVIEW" && <button className="ml-2 text-green-700 hover:underline" onClick={() => void act(() => api.post(`${RES}/cost-evidence/${r.id}/approve`), "Đã duyệt evidence.")} data-testid={`roadmap-cost-approve-${r.id}`}>Duyệt</button>}
                {perm.approve && r.status === "APPROVED" && <button className="ml-2 text-red-600 hover:underline" onClick={() => { const reason = window.prompt("Lý do retire evidence? (bắt buộc)") ?? ""; if (reason.trim()) void act(() => api.post(`${RES}/cost-evidence/${r.id}/retire`, { reason }), "Đã retire evidence."); }}>Retire</button>}
                {perm.manage && (r.status === "APPROVED" || r.status === "RETIRED") && <button className="ml-2 text-brand hover:underline" onClick={() => void act(() => api.post(`${RES}/cost-evidence/${r.id}/new-version`), "Đã tạo version mới (Draft).")}>Version mới</button>}
              </td></tr>
          ))}{rows.length === 0 && <tr><td colSpan={7} className="py-4 text-center text-slate-400">Chưa có cost evidence nào (đúng: production không seed giá/chi phí).</td></tr>}</tbody></table>
      </div>
      {perm.manage && (
        <div className="mt-3 grid grid-cols-4 gap-2 rounded-xl border border-slate-200 p-3">
          <F label="Mã evidence"><input className={inp} value={d.evidence_code} onChange={(e) => setD({ ...d, evidence_code: e.target.value })} data-testid="roadmap-cost-code" /></F>
          <F label="Loại chi phí"><select className={inp} value={d.cost_family} onChange={(e) => setD({ ...d, cost_family: e.target.value, source_kind: "" })}>{opts.cost_families.map((f) => <option key={f}>{f}</option>)}</select></F>
          <F label="Số tiền (Decimal)"><input className={inp} value={d.amount} onChange={(e) => setD({ ...d, amount: e.target.value })} data-testid="roadmap-cost-amount" /></F>
          <F label="Currency (3 chữ in hoa)"><input className={inp} value={d.currency} maxLength={3} onChange={(e) => setD({ ...d, currency: e.target.value.toUpperCase() })} /></F>
          {machine ? <>
            <F label="Loại máy"><input className={inp} value={d.machine_type_code} onChange={(e) => setD({ ...d, machine_type_code: e.target.value })} /></F>
            <F label="Model id (tùy chọn)"><input className={inp} value={d.machine_model_id} onChange={(e) => setD({ ...d, machine_model_id: e.target.value })} /></F>
            <F label="Candidate id (tùy chọn)"><input className={inp} value={d.future_candidate_id} onChange={(e) => setD({ ...d, future_candidate_id: e.target.value })} /></F>
            <F label="Price basis (bắt buộc)"><select className={inp} value={d.price_basis} onChange={(e) => setD({ ...d, price_basis: e.target.value })}><option value="" />{opts.machine_price_bases.map((b) => <option key={b}>{b}</option>)}</select></F>
          </> : <>
            <F label="Scope"><select className={inp} value={d.scope_type} onChange={(e) => setD({ ...d, scope_type: e.target.value })}>{opts.scope_types.map((t) => <option key={t}>{t}</option>)}</select></F>
            <F label="Factory (khi FACTORY)"><input className={inp} value={d.scope_value} disabled={d.scope_type !== "FACTORY"} onChange={(e) => setD({ ...d, scope_value: e.target.value })} /></F>
            <F label="Kỳ chi phí (khớp kỳ action)"><select className={inp} value={d.cost_period} onChange={(e) => setD({ ...d, cost_period: e.target.value })}>{opts.period_types.map((t) => <option key={t}>{t}</option>)}</select></F>
          </>}
          <F label="Loại nguồn"><select className={inp} value={d.source_kind} onChange={(e) => setD({ ...d, source_kind: e.target.value })}><option value="" />{kinds.map((k) => <option key={k} value={k}>{k}{opts.cost_blocked_source_kinds.includes(k) ? " (không duyệt được)" : ""}</option>)}</select></F>
          <div className="col-span-2"><F label="Source ref"><input className={inp} value={d.source_ref} onChange={(e) => setD({ ...d, source_ref: e.target.value })} /></F></div>
          <F label="Vendor (bắt buộc với SUPPLIER_QUOTATION)"><input className={inp} value={d.vendor} onChange={(e) => setD({ ...d, vendor: e.target.value })} /></F>
          <F label="Ngày evidence"><input className={inp} type="date" value={d.evidence_date} onChange={(e) => setD({ ...d, evidence_date: e.target.value })} /></F>
          <F label="Quote hiệu lực đến"><input className={inp} type="date" value={d.quote_valid_until} onChange={(e) => setD({ ...d, quote_valid_until: e.target.value })} /></F>
          <F label="Hiệu lực từ"><input className={inp} type="date" value={d.effective_from} onChange={(e) => setD({ ...d, effective_from: e.target.value })} /></F>
          <F label="Hiệu lực đến"><input className={inp} type="date" value={d.effective_to} onChange={(e) => setD({ ...d, effective_to: e.target.value })} /></F>
          <div className="col-span-4 text-right"><button className={primary} disabled={!d.evidence_code.trim() || !d.amount} onClick={() => void create()} data-testid="roadmap-cost-save">+ Tạo evidence Draft</button></div>
        </div>
      )}
      {perm.manage && (
        <div className="mt-3 grid grid-cols-6 gap-2 rounded-xl border border-slate-200 p-3">
          <div className="col-span-6 text-[11px] font-semibold text-slate-500">Asset ref (chỉ tham chiếu ảnh/datasheet/3D — không upload/tải/render; https:// hoặc asset_ref nội bộ)</div>
          <F label="Đối tượng"><select className={inp} value={asset.subject_type} onChange={(e) => setAsset({ ...asset, subject_type: e.target.value })}>{opts.asset_subject_types.map((t) => <option key={t}>{t}</option>)}</select></F>
          <F label="Mã / id"><input className={inp} value={asset.subject_ref} onChange={(e) => setAsset({ ...asset, subject_ref: e.target.value })} /></F>
          <F label="Loại asset"><select className={inp} value={asset.asset_kind} onChange={(e) => setAsset({ ...asset, asset_kind: e.target.value })}>{opts.asset_kinds.map((t) => <option key={t}>{t}</option>)}</select></F>
          <div className="col-span-2"><F label="URI https://"><input className={inp} value={asset.uri} onChange={(e) => setAsset({ ...asset, uri: e.target.value })} /></F></div>
          <F label="hoặc asset_ref"><input className={inp} value={asset.asset_ref} onChange={(e) => setAsset({ ...asset, asset_ref: e.target.value })} /></F>
          <div className="col-span-6 text-right"><button className={btn} disabled={!asset.subject_ref || (!asset.uri && !asset.asset_ref)} onClick={() => void addAsset()}>+ Thêm asset ref</button></div>
        </div>
      )}
    </Modal>
  );
}

interface PkgRow { id: number; package_code: string; package_no: number; status: string }
interface PkgLine { item_id: number; proposal_type: string; planned_effective_date: string; selected_quantity: number | null; cost_class: string | null; cost_status: string; cost_status_reason: string; amount: string | null; currency: string | null; cost_period: string | null; milestone_bucket: string; warnings: string[]; evidence: { evidence_code: string; evidence_version: number } | null }
interface PkgDetail extends PkgRow {
  frozen: boolean; editable: boolean; reviewed_by: string; approved_by: string; package_fingerprint: string; bindings: { action_item_id: number; evidence_id: number; machine_model_id: number | null; future_candidate_id: number | null }[];
  live_warnings: { code: string; detail: string; evidence: string }[];
  package: { completeness: { pricing: string; supported_action_count: number; priced_action_count: number; unresolved_count: number }; warning_codes: string[]; selected_actions: PkgLine[]; unresolved_actions: PkgLine[];
    machine_details: { item_id: number; machine_type_code: string; selected_quantity: number; price_basis: string | null; details: { machine_type: { name: string; reference_placeholders: { note: string } } | null; machine_model: { brand: string; model: string } | null; future_candidate: { candidate_code: string } | null; asset_refs: { asset_kind: string; uri: string; asset_ref: string }[] } }[];
    labor_details: { item_id: number; selected_headcount: number; productivity: { value: number; unit: string } }[];
    direct_cost_summary: { MACHINE_CAPEX: { currency: string; amount: string; by_milestone_bucket: Record<string, string> }[]; LABOR_RECURRING_COST: { currency: string; cost_period: string; amount: string }[]; labor_run_rate_by_milestone: { milestone_code: string; currency: string; cost_period: string; run_rate_per_period: string }[]; UNPRICED_ACTIONS: { item_id: number; proposal_type: string; reason: string }[] } };
}

/** Task 8: Executive Decision Package của một Action Plan version APPROVED. Bind evidence do user chọn; không auto-pick, không grand total, không ranking. */
function DecisionPackagePanel({ apVersionId, items, perm, setMsg }: { apVersionId: number; items: ApItem[]; perm: { manage: boolean; approve: boolean; archived?: boolean }; setMsg: (m: Msg) => void }) {
  const [pkgs, setPkgs] = useState<PkgRow[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [det, setDet] = useState<PkgDetail | null>(null);
  const [evs, setEvs] = useState<CostEv[]>([]);
  const [b, setB] = useState({ item: "", evidence: "", model: "", cand: "" });
  const [drawer, setDrawer] = useState<{ title: string; data: unknown } | null>(null);
  const loadList = useCallback(async () => setPkgs((await api.get<PkgRow[]>(`${RES}/decision-packages?action_plan_version_id=${apVersionId}`)).data), [apVersionId]);
  const loadDet = useCallback(async (id: number) => setDet((await api.get<PkgDetail>(`${RES}/decision-packages/${id}`)).data), []);
  useEffect(() => { loadList().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); api.get<CostEv[]>(`${RES}/cost-evidence?status=APPROVED`).then((r) => setEvs(r.data)).catch(() => undefined); }, [loadList, setMsg]);
  useEffect(() => { if (sel !== null) loadDet(sel).catch((e) => setMsg({ ok: false, text: errorMessage(e) })); else setDet(null); }, [sel, loadDet, setMsg]);
  const act = async (fn: () => Promise<unknown>, ok: string) => { try { await fn(); setMsg({ ok: true, text: ok }); await loadList(); if (sel !== null) await loadDet(sel); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  const create = async () => { try { const v = (await api.post<PkgDetail>(`${RES}/action-plan-versions/${apVersionId}/decision-packages`, {})).data; await loadList(); setSel(v.id); setMsg({ ok: true, text: `Đã tạo ${v.package_code} (Draft).` }); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  const counted = items.filter((i) => i.inclusion_status === "COUNTED");
  const pickedItem = counted.find((i) => String(i.id) === b.item);
  const fam = pickedItem?.proposal_type === "MACHINE_PURCHASE" ? "MACHINE_UNIT_PRICE" : "LABOR_COST_PER_WORKER_PERIOD";
  const s = det?.package;
  const compare = async (otherId: number) => { try { setDrawer({ title: `So sánh package #${det?.id} ↔ #${otherId} (không xếp hạng)`, data: (await api.get(`${RES}/decision-package-compare/${det!.id}/${otherId}`)).data }); } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } };
  return (
    <div className="space-y-3 rounded-xl border border-indigo-200 p-3" data-testid="roadmap-decision-package">
      <div className="flex flex-wrap items-center gap-2">
        <h5 className="text-xs font-bold">Executive Decision Package (evidence chi phí — không tối ưu, không xếp hạng, không ROI)</h5><span className="flex-1" />
        {perm.manage && <button className={btn} onClick={() => void create()} data-testid="roadmap-pkg-create">+ Tạo Decision Package</button>}
      </div>
      <div className="flex flex-wrap gap-2 text-xs">{pkgs.length === 0 && <span className="text-slate-400">Chưa có package.</span>}{pkgs.map((p) => <button key={p.id} onClick={() => setSel(p.id)} className={`rounded-full border px-3 py-1 ${sel === p.id ? "border-brand bg-brand/10" : "border-slate-300"}`}>{p.package_code} <Chip s={p.status} /></button>)}</div>
      {det && s && (
        <div className="space-y-3" data-testid="roadmap-pkg-detail">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <b>{det.package_code}</b><Chip s={det.status} /><Chip s={s.completeness.pricing} /><span className="text-slate-400">{det.frozen ? `đóng băng · fp ${det.package_fingerprint}` : "preview (tính lại từ evidence hiện tại)"} · {s.completeness.priced_action_count}/{s.completeness.supported_action_count} action đã định giá · {s.completeness.unresolved_count} unresolved</span><span className="flex-1" />
            {perm.manage && det.status === "DRAFT" && <button className={btn} onClick={() => void act(() => api.post(`${RES}/decision-packages/${det.id}/submit-review`), "Đã đóng băng & chuyển UNDER_REVIEW (bạn là reviewer).")} data-testid="roadmap-pkg-review">Gửi review (đóng băng)</button>}
            {perm.approve && !perm.archived && det.status === "UNDER_REVIEW" && <button className={primary} onClick={() => void act(() => api.post(`${RES}/decision-packages/${det.id}/approve`), "Đã duyệt package (không thực thi mua/tuyển).")} data-testid="roadmap-pkg-approve">Duyệt</button>}
            {perm.approve && det.status === "APPROVED" && <button className={btn} onClick={() => { const reason = window.prompt("Lý do archive? (bắt buộc)") ?? ""; if (reason.trim()) void act(() => api.post(`${RES}/decision-packages/${det.id}/archive`, { reason }), "Đã archive."); }}>Archive</button>}
            <select className={`${inp} !w-44`} value="" onChange={(e) => { if (e.target.value) void compare(Number(e.target.value)); }}><option value="">So sánh với…</option>{pkgs.filter((p) => p.id !== det.id).map((p) => <option key={p.id} value={p.id}>{p.package_code}</option>)}</select>
          </div>
          {det.live_warnings.map((w) => <p key={w.evidence} className="rounded-lg border border-amber-300/60 px-3 py-1 text-xs text-amber-700">{w.code}: {w.evidence} — {w.detail}</p>)}
          {det.editable && perm.manage && (
            <div className="grid grid-cols-5 gap-2 rounded-lg border border-slate-200 p-2">
              <div className="col-span-2"><F label="Item COUNTED (labor/machine)"><select className={inp} value={b.item} onChange={(e) => setB({ ...b, item: e.target.value, evidence: "" })} data-testid="roadmap-pkg-item"><option value="" />{counted.map((i) => <option key={i.id} value={i.id}>{PTYPE_LABEL[i.proposal_type]} · {i.source_milestone_code} · {i.selected_quantity} {i.unit} · {i.planned_effective_date}</option>)}</select></F></div>
              <div className="col-span-2"><F label="Evidence APPROVED (user chọn tường minh)"><select className={inp} value={b.evidence} onChange={(e) => setB({ ...b, evidence: e.target.value })} data-testid="roadmap-pkg-evidence"><option value="" />{evs.filter((e) => e.cost_family === fam).map((e) => <option key={e.id} value={e.id}>{e.evidence_code}@v{e.evidence_version} · {e.amount} {e.currency}{e.cost_period ? `/${e.cost_period}` : ""}</option>)}</select></F></div>
              <div className="flex items-end"><button className={primary} disabled={!b.item || !b.evidence} data-testid="roadmap-pkg-bind" onClick={() => void act(() => api.post(`${RES}/decision-packages/${det.id}/bindings`, { action_item_id: Number(b.item), evidence_id: Number(b.evidence), machine_model_id: b.model ? Number(b.model) : undefined, future_candidate_id: b.cand ? Number(b.cand) : undefined }), "Đã bind evidence.")}>Bind</button></div>
              {fam === "MACHINE_UNIT_PRICE" && <><F label="Model id (tùy chọn)"><input className={inp} value={b.model} onChange={(e) => setB({ ...b, model: e.target.value })} /></F><F label="Candidate id (tùy chọn)"><input className={inp} value={b.cand} onChange={(e) => setB({ ...b, cand: e.target.value })} /></F></>}
              <p className="col-span-5 text-[11px] text-slate-500">Mỗi item dùng đúng 1 evidence do bạn chọn (không tự chọn “mới nhất/rẻ nhất”). Thiếu evidence ⇒ UNPRICED. Bỏ bind: xóa bằng nút “Bỏ bind” ở bảng dưới.</p>
            </div>
          )}
          <div className="overflow-x-auto"><table className="w-full text-xs" data-testid="roadmap-pkg-lines">
            <thead><tr><th className={th}>Action</th><th className={th}>Ngày / bucket</th><th className={`${th} text-right`}>Số lượng</th><th className={th}>Evidence</th><th className={`${th} text-right`}>Chi phí trực tiếp</th><th className={th}>Định giá</th><th /></tr></thead>
            <tbody>{[...s.selected_actions, ...s.unresolved_actions].map((l) => (
              <tr key={l.item_id} className="border-t border-slate-100 align-top">
                <td className="px-3 py-1.5">{PTYPE_LABEL[l.proposal_type] ?? l.proposal_type}<div className="text-[10px] text-slate-400">{l.cost_class ?? "không hỗ trợ giá"}</div></td>
                <td className="px-3">{l.planned_effective_date}<div className="text-[10px] text-slate-400">bucket {l.milestone_bucket} (planning, không phải ngày thanh toán)</div></td>
                <td className="px-3 text-right">{l.selected_quantity ?? "—"}</td>
                <td className="px-3 font-mono text-[11px]">{l.evidence ? `${l.evidence.evidence_code}@v${l.evidence.evidence_version}` : "—"}</td>
                <td className="px-3 text-right font-mono">{l.amount ? `${l.amount} ${l.currency}${l.cost_period ? `/${l.cost_period}` : ""}` : "—"}</td>
                <td className="px-3"><Chip s={l.cost_status} />{l.cost_status_reason && <div className="text-[10px] text-amber-700">{l.cost_status_reason}</div>}</td>
                <td className="whitespace-nowrap px-3 text-right">{det.editable && perm.manage && det.bindings.some((x) => x.action_item_id === l.item_id) && <button className="text-red-600 hover:underline" onClick={() => void act(() => api.delete(`${RES}/decision-packages/${det.id}/bindings/${l.item_id}`), "Đã bỏ bind.")}>Bỏ bind</button>}</td>
              </tr>
            ))}</tbody></table></div>
          <div className="grid gap-3 md:grid-cols-2" data-testid="roadmap-pkg-summary">
            <div className="rounded-lg border border-slate-200 p-2 text-xs"><b>Machine CAPEX</b> (theo currency)
              {s.direct_cost_summary.MACHINE_CAPEX.length === 0 ? <div className="text-slate-400">chưa có action máy nào được định giá</div> : s.direct_cost_summary.MACHINE_CAPEX.map((g) => <div key={g.currency}>{g.currency}: <span className="font-mono">{g.amount}</span><div className="text-[10px] text-slate-400">{Object.entries(g.by_milestone_bucket).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div></div>)}</div>
            <div className="rounded-lg border border-slate-200 p-2 text-xs"><b>Labor Recurring Cost</b> (run-rate mỗi kỳ, theo currency + kỳ; không nhân số kỳ)
              {s.direct_cost_summary.LABOR_RECURRING_COST.length === 0 ? <div className="text-slate-400">chưa có action lao động nào được định giá</div> : s.direct_cost_summary.LABOR_RECURRING_COST.map((g) => <div key={`${g.currency}${g.cost_period}`}>{g.currency}/{g.cost_period}: <span className="font-mono">{g.amount}</span></div>)}</div>
          </div>
          <p className="text-[11px] text-slate-500">Không có “Total Investment”: CAPEX máy và chi phí lao động định kỳ được giữ riêng; không cộng khác currency/kỳ; không ROI/NPV/IRR/payback.</p>
          {s.direct_cost_summary.UNPRICED_ACTIONS.length > 0 && <p className="text-xs text-amber-700">Unpriced: {s.direct_cost_summary.UNPRICED_ACTIONS.map((u) => `${PTYPE_LABEL[u.proposal_type] ?? u.proposal_type} (${u.reason})`).join(", ")}</p>}
          {s.warning_codes.length > 0 && <p className="text-xs text-amber-700" data-testid="roadmap-pkg-warnings">Cảnh báo: {s.warning_codes.join(", ")}</p>}
          <div className="flex flex-wrap gap-2 text-xs">
            {s.machine_details.map((m) => <button key={m.item_id} className={btn} onClick={() => setDrawer({ title: `Chi tiết máy — ${m.machine_type_code}`, data: m })}>Máy {m.machine_type_code} ×{m.selected_quantity}{m.details?.machine_model ? ` · ${m.details.machine_model.brand} ${m.details.machine_model.model}` : ""}{m.details && m.details.asset_refs.length > 0 ? ` · ${m.details.asset_refs.length} asset` : ""}</button>)}
            {s.labor_details.map((l) => <button key={l.item_id} className={btn} onClick={() => setDrawer({ title: "Chi tiết lao động", data: l })}>Lao động ×{l.selected_headcount} · năng suất {l.productivity.value} {l.productivity.unit}</button>)}
            <button className={btn} onClick={() => setDrawer({ title: "Package JSON (snapshot)", data: det.package })}>Snapshot / evidence</button>
          </div>
        </div>
      )}
      {drawer && <Modal title={drawer.title} onClose={() => setDrawer(null)} wide><J v={drawer.data} /></Modal>}
    </div>
  );
}
