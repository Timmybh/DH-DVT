import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, useParams } from "react-router-dom";
import { api, errorMessage, PlanVersion } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { dateVi, num } from "../../lib/format";
import { isoWeek, weekRange } from "../../lib/weeks";

const SECTIONS = [
  { key: "capacity", label: "Năng suất (Capacity)" },
  { key: "machines", label: "Máy móc" },
  { key: "labor", label: "Lao động" },
  { key: "release", label: "Lịch giải phóng" },
];
const input = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm";
const chip = "pg-chip";

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between">
          <h3 className="text-lg font-bold text-slate-900">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Đóng">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Capacity Definition
interface Cap {
  id: number; factory_code: string; line: string; style_cc: string; model_code: string; process: string; worker_count: number | null; working_minutes: number | null;
  capacity_per_day: number; effective_from: string | null; effective_to: string | null; source: string; owner: string; status: string; version: number; notes: string;
}

function CapacityTab({ canManage }: { canManage: boolean }) {
  const [rows, setRows] = useState<Cap[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("ACTIVE");
  const [factory, setFactory] = useState("");
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<Partial<Cap> | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [probe, setProbe] = useState({ factory_code: "XN1", line: "", style_cc: "", model_code: "" });
  const [probeOut, setProbeOut] = useState<string>("");

  const load = useCallback(async () => {
    const r = await api.get<{ total: number; rows: Cap[] }>("/planning/resources/capacity", { params: { status, factory: factory || undefined, q: q || undefined, limit: 300 } });
    setRows(r.data.rows);
    setTotal(r.data.total);
  }, [status, factory, q]);
  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })), 200);
    return () => clearTimeout(t);
  }, [load]);

  const save = async () => {
    if (!edit) return;
    try {
      const body = { ...edit, capacity_per_day: Number(edit.capacity_per_day), worker_count: edit.worker_count === null || edit.worker_count === undefined || (edit.worker_count as unknown) === "" ? null : Number(edit.worker_count), effective_from: edit.effective_from || null, effective_to: edit.effective_to || null };
      if (edit.id) await api.put(`/planning/resources/capacity/${edit.id}`, body);
      else await api.post("/planning/resources/capacity", body);
      setEdit(null);
      setMsg({ ok: true, text: edit.id ? "Đã tạo phiên bản mới, bản cũ chuyển RETIRED." : "Đã thêm định nghĩa năng suất." });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const retire = async (c: Cap) => {
    if (!window.confirm(`Retire định nghĩa năng suất #${c.id}?`)) return;
    try {
      await api.post(`/planning/resources/capacity/${c.id}/retire`);
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const importPlan = async () => {
    try {
      const r = await api.post<{ created: number; groups: number }>("/planning/resources/capacity/import-plan");
      setMsg({ ok: true, text: `Đã tạo ${r.data.created} định nghĩa (nguồn WORKBOOK) từ ${r.data.groups} tổ hợp XN/chuyền/mã hàng trong file kế hoạch. Cần IE xác nhận.` });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const resolve = async () => {
    try {
      const r = await api.post<{ found: boolean; definition: (Cap & { capacity_per_day: number }) | null }>("/planning/resources/capacity/resolve", probe);
      setProbeOut(r.data.found && r.data.definition ? `${num(r.data.definition.capacity_per_day)} pcs/ngày — nguồn ${r.data.definition.source} v${r.data.definition.version} (định nghĩa #${r.data.definition.id})` : "Không có định nghĩa nào áp dụng.");
    } catch (e) {
      setProbeOut(errorMessage(e));
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">Năng suất chuẩn (pcs/ngày) theo XN / chuyền / mã hàng. Định nghĩa cụ thể nhất còn hiệu lực được dùng; sửa sẽ tạo phiên bản mới, không ghi đè lịch sử. Trường để trống = áp dụng cho tất cả.</p>
      <div className="flex flex-wrap items-center gap-2">
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="Trạng thái"><option value="ACTIVE">ACTIVE</option><option value="RETIRED">RETIRED</option><option value="ALL">Tất cả</option></select>
        <select value={factory} onChange={(e) => setFactory(e.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="Xí nghiệp"><option value="">Mọi XN</option>{["XN1", "XN2", "XN3"].map((f) => <option key={f}>{f}</option>)}</select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm mã hàng / chuyền..." className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Tìm" />
        <span className="text-xs text-slate-400">{num(total)} định nghĩa</span>
        <span className="flex-1" />
        {canManage && <button onClick={importPlan} className="rounded-full border border-slate-300 px-4 py-1.5 text-xs">Nhập từ file kế hoạch</button>}
        {canManage && <button onClick={() => setEdit({ factory_code: "", line: "", style_cc: "", model_code: "", process: "", source: "IE", capacity_per_day: 0 })} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white">+ Thêm</button>}
      </div>
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}

      <div className="rounded-xl border border-slate-200 p-3 text-sm">
        <p className="mb-2 text-xs font-bold uppercase text-slate-400">Tra cứu: năng suất nào sẽ được áp dụng?</p>
        <div className="flex flex-wrap items-center gap-2">
          {(["factory_code", "line", "style_cc", "model_code"] as const).map((k) => (
            <input key={k} value={probe[k]} onChange={(e) => setProbe({ ...probe, [k]: e.target.value })} placeholder={{ factory_code: "XN", line: "Chuyền", style_cc: "Style/CC", model_code: "Model" }[k]} className="w-28 rounded-lg border border-slate-200 px-2 py-1 text-xs" aria-label={k} />
          ))}
          <button onClick={resolve} className="rounded-full border border-slate-300 px-3 py-1 text-xs">Tra cứu</button>
          {probeOut && <span className="text-xs text-slate-600" data-testid="probe-out">{probeOut}</span>}
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full min-w-[980px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="px-4 py-2.5">XN</th><th>Chuyền</th><th>Style/CC</th><th>Model</th><th className="text-right">Năng suất/ngày</th><th className="text-right">Worker</th><th>Nguồn</th><th>Hiệu lực</th><th>Phiên bản</th><th>Trạng thái</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-b border-slate-50" data-testid={`cap-${c.id}`}>
                <td className="px-4 py-1.5">{c.factory_code || "Mọi XN"}</td><td>{c.line || "—"}</td><td>{c.style_cc || "—"}</td><td>{c.model_code || "—"}</td>
                <td className="text-right font-semibold tabular-nums">{num(c.capacity_per_day)}</td><td className="text-right">{c.worker_count ?? "—"}</td>
                <td><span className={`${chip} pg-known`}>{c.source}</span></td>
                <td className="text-xs text-slate-500">{c.effective_from ? dateVi(c.effective_from) : "—"} → {c.effective_to ? dateVi(c.effective_to) : "—"}</td>
                <td>v{c.version}</td>
                <td><span className={`${chip} ${c.status === "ACTIVE" ? "pg-ok" : "pg-unk"}`}>{c.status}</span></td>
                <td className="whitespace-nowrap pr-4 text-right text-xs">
                  {canManage && c.status === "ACTIVE" && <button onClick={() => setEdit(c)} className="mr-2 text-brand hover:underline">Sửa (phiên bản mới)</button>}
                  {canManage && c.status === "ACTIVE" && <button onClick={() => retire(c)} className="text-red-500 hover:underline">Retire</button>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={11} className="py-8 text-center text-slate-400">Chưa có định nghĩa năng suất — dùng "Nhập từ file kế hoạch" hoặc "+ Thêm".</td></tr>}
          </tbody>
        </table>
      </div>

      {edit && (
        <Modal title={edit.id ? `Sửa năng suất #${edit.id} (tạo v${(edit.version ?? 1) + 1})` : "Thêm định nghĩa năng suất"} onClose={() => setEdit(null)}>
          <div className="grid grid-cols-2 gap-3">
            {(["factory_code", "line", "style_cc", "model_code"] as const).map((k) => (
              <label key={k} className="block text-xs text-slate-500">{{ factory_code: "Xí nghiệp (trống = mọi XN)", line: "Chuyền (trống = mọi chuyền)", style_cc: "Style/CC (trống = mọi mã)", model_code: "Model" }[k]}
                <input className={input} value={(edit[k] as string) ?? ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />
              </label>
            ))}
            <label className="block text-xs text-slate-500">Năng suất (pcs/ngày)<input type="number" className={input} value={edit.capacity_per_day ?? ""} onChange={(e) => setEdit({ ...edit, capacity_per_day: e.target.value as unknown as number })} /></label>
            <label className="block text-xs text-slate-500">Số công nhân<input type="number" className={input} value={edit.worker_count ?? ""} onChange={(e) => setEdit({ ...edit, worker_count: e.target.value === "" ? null : Number(e.target.value) })} /></label>
            <label className="block text-xs text-slate-500">Hiệu lực từ<input type="date" className={input} value={edit.effective_from ?? ""} onChange={(e) => setEdit({ ...edit, effective_from: e.target.value })} /></label>
            <label className="block text-xs text-slate-500">Hiệu lực đến<input type="date" className={input} value={edit.effective_to ?? ""} onChange={(e) => setEdit({ ...edit, effective_to: e.target.value })} /></label>
            <label className="block text-xs text-slate-500">Nguồn<select className={input} value={edit.source} onChange={(e) => setEdit({ ...edit, source: e.target.value })}>{["IE", "LEAN", "CI", "MANUAL"].map((s) => <option key={s}>{s}</option>)}</select></label>
            <label className="block text-xs text-slate-500">Người phụ trách<input className={input} value={edit.owner ?? ""} onChange={(e) => setEdit({ ...edit, owner: e.target.value })} /></label>
          </div>
          <label className="mt-3 block text-xs text-slate-500">Ghi chú<input className={input} value={edit.notes ?? ""} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></label>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setEdit(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={save} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">Lưu</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Máy móc
interface Mach { id: number; factory_code: string; line: string; machine_type: string; quantity: number; nominal_output_per_day: number | null; efficiency: number | null; changeover_minutes: number | null; planned_downtime_pct: number | null; maintenance_status: string; is_bottleneck: boolean; notes: string }
interface Req { id: number; style_cc: string; machine_type: string; machine_name: string; quantity: number; source: string }

function MachinesTab({ canManage }: { canManage: boolean }) {
  const [caps, setCaps] = useState<Mach[]>([]);
  const [reqs, setReqs] = useState<Req[]>([]);
  const [types, setTypes] = useState<{ code: string; name: string }[]>([]);
  const [factory, setFactory] = useState("");
  const [edit, setEdit] = useState<Partial<Mach> | null>(null);
  const [newReq, setNewReq] = useState({ style_cc: "", machine_type: "", quantity: 1 });
  const [rq, setRq] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const [c, r, t] = await Promise.all([
      api.get<Mach[]>("/planning/resources/machine-capacity", { params: { factory: factory || undefined } }),
      api.get<Req[]>("/planning/resources/machine-requirements", { params: { q: rq || undefined } }),
      api.get<{ code: string; name: string }[]>("/planning/resources/machine-types"),
    ]);
    setCaps(c.data); setReqs(r.data); setTypes(t.data);
  }, [factory, rq]);
  useEffect(() => {
    load().catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, [load]);

  const saveMach = async () => {
    if (!edit) return;
    try {
      const num0 = (v: unknown) => (v === "" || v === null || v === undefined ? null : Number(v));
      const body = { ...edit, quantity: Number(edit.quantity ?? 0), nominal_output_per_day: num0(edit.nominal_output_per_day), efficiency: num0(edit.efficiency), changeover_minutes: num0(edit.changeover_minutes), planned_downtime_pct: num0(edit.planned_downtime_pct) };
      if (edit.id) await api.put(`/planning/resources/machine-capacity/${edit.id}`, body);
      else await api.post("/planning/resources/machine-capacity", body);
      setEdit(null);
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const addReq = async () => {
    try {
      await api.post("/planning/resources/machine-requirements", { ...newReq, machine_type: newReq.machine_type.toUpperCase(), quantity: Number(newReq.quantity) });
      setNewReq({ style_cc: "", machine_type: "", quantity: 1 });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const delReq = async (id: number) => {
    await api.delete(`/planning/resources/machine-requirements/${id}`).catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
    await load();
  };
  const typeName = (code: string) => types.find((t) => t.code === code)?.name ?? "";

  return (
    <div className="space-y-6">
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-bold text-slate-900">Máy theo chuyền (Machine Capacity)</h2>
          <select value={factory} onChange={(e) => setFactory(e.target.value)} className="rounded-lg border border-slate-200 px-2 py-1 text-sm" aria-label="Xí nghiệp"><option value="">Mọi XN</option>{["XN1", "XN2", "XN3"].map((f) => <option key={f}>{f}</option>)}</select>
          <span className="flex-1" />
          {canManage && <button onClick={() => setEdit({ factory_code: "XN1", line: "", machine_type: "", quantity: 1, maintenance_status: "OK", is_bottleneck: false })} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white">+ Thêm</button>}
        </div>
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead><tr className="border-b border-slate-100 text-xs uppercase text-slate-400"><th className="px-4 py-2.5">XN</th><th>Chuyền</th><th>Nhóm máy</th><th className="text-right">Số máy</th><th className="text-right">Công suất/ngày</th><th className="text-right">OEE</th><th>Bảo trì</th><th>Nút thắt</th><th /></tr></thead>
            <tbody>
              {caps.map((m) => (
                <tr key={m.id} className="border-b border-slate-50" data-testid={`mach-${m.id}`}>
                  <td className="px-4 py-1.5">{m.factory_code}</td><td>{m.line}</td><td>{m.machine_type}<span className="ml-1 text-xs text-slate-400">{typeName(m.machine_type)}</span></td>
                  <td className="text-right font-semibold">{m.quantity}</td><td className="text-right">{m.nominal_output_per_day ? num(m.nominal_output_per_day) : "—"}</td><td className="text-right">{m.efficiency ?? "—"}</td>
                  <td><span className={`${chip} ${m.maintenance_status === "OK" ? "pg-ok" : m.maintenance_status === "DOWN" ? "pg-late" : "pg-adv"}`}>{m.maintenance_status}</span></td>
                  <td>{m.is_bottleneck ? <span className={`${chip} pg-late`}>Nút thắt</span> : "—"}</td>
                  <td className="pr-4 text-right text-xs">{canManage && <button onClick={() => setEdit(m)} className="text-brand hover:underline">Sửa</button>}</td>
                </tr>
              ))}
              {caps.length === 0 && <tr><td colSpan={9} className="py-6 text-center text-slate-400">Chưa khai báo máy theo chuyền. Kiểm tra thiếu máy chỉ chạy khi cả yêu cầu máy của mã hàng và máy của chuyền đều được khai báo.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-bold text-slate-900">Yêu cầu máy theo mã hàng</h2>
          <input value={rq} onChange={(e) => setRq(e.target.value)} placeholder="Tìm mã hàng..." className="rounded-lg border border-slate-200 px-3 py-1 text-sm" aria-label="Tìm mã hàng" />
        </div>
        {canManage && (
          <div className="flex flex-wrap items-end gap-2 text-xs">
            <input value={newReq.style_cc} onChange={(e) => setNewReq({ ...newReq, style_cc: e.target.value })} placeholder="Style/CC" className="w-32 rounded-lg border border-slate-200 px-2 py-1.5" aria-label="Style/CC" />
            <input value={newReq.machine_type} list="machine-types" onChange={(e) => setNewReq({ ...newReq, machine_type: e.target.value })} placeholder="Nhóm máy" className="w-32 rounded-lg border border-slate-200 px-2 py-1.5" aria-label="Nhóm máy" />
            <datalist id="machine-types">{types.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}</datalist>
            <input type="number" min={1} value={newReq.quantity} onChange={(e) => setNewReq({ ...newReq, quantity: Number(e.target.value) })} className="w-20 rounded-lg border border-slate-200 px-2 py-1.5" aria-label="Số lượng" />
            <button onClick={addReq} disabled={!newReq.style_cc || !newReq.machine_type} className="rounded-full bg-brand px-4 py-1.5 font-semibold text-white disabled:opacity-40">Lưu yêu cầu</button>
          </div>
        )}
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead><tr className="border-b border-slate-100 text-xs uppercase text-slate-400"><th className="px-4 py-2.5">Style/CC</th><th>Nhóm máy</th><th className="text-right">Số máy cần</th><th>Nguồn</th><th /></tr></thead>
            <tbody>
              {reqs.map((r) => (
                <tr key={r.id} className="border-b border-slate-50">
                  <td className="px-4 py-1.5">{r.style_cc}</td><td>{r.machine_type}<span className="ml-1 text-xs text-slate-400">{r.machine_name}</span></td><td className="text-right font-semibold">{r.quantity}</td>
                  <td><span className={`${chip} ${r.source === "QTCN" ? "pg-viol" : "pg-known"}`}>{r.source}</span></td>
                  <td className="pr-4 text-right text-xs">{canManage && <button onClick={() => delReq(r.id)} className="text-red-500 hover:underline">Xóa</button>}</td>
                </tr>
              ))}
              {reqs.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-slate-400">Chưa có yêu cầu máy nào (đồng bộ từ Quy trình công nghệ eGMF hoặc nhập tay).</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {edit && (
        <Modal title={edit.id ? "Sửa máy theo chuyền" : "Thêm máy theo chuyền"} onClose={() => setEdit(null)}>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs text-slate-500">Xí nghiệp<select className={input} value={edit.factory_code} onChange={(e) => setEdit({ ...edit, factory_code: e.target.value })}>{["XN1", "XN2", "XN3"].map((f) => <option key={f}>{f}</option>)}</select></label>
            <label className="block text-xs text-slate-500">Chuyền<input className={input} value={edit.line ?? ""} onChange={(e) => setEdit({ ...edit, line: e.target.value })} /></label>
            <label className="block text-xs text-slate-500">Nhóm máy<input list="machine-types" className={input} value={edit.machine_type ?? ""} onChange={(e) => setEdit({ ...edit, machine_type: e.target.value.toUpperCase() })} /></label>
            <label className="block text-xs text-slate-500">Số máy<input type="number" className={input} value={edit.quantity ?? 0} onChange={(e) => setEdit({ ...edit, quantity: Number(e.target.value) })} /></label>
            <label className="block text-xs text-slate-500">Công suất danh định (pcs/ngày)<input type="number" className={input} value={edit.nominal_output_per_day ?? ""} onChange={(e) => setEdit({ ...edit, nominal_output_per_day: e.target.value === "" ? null : Number(e.target.value) })} /></label>
            <label className="block text-xs text-slate-500">Hiệu suất OEE (0–1)<input type="number" step="0.05" className={input} value={edit.efficiency ?? ""} onChange={(e) => setEdit({ ...edit, efficiency: e.target.value === "" ? null : Number(e.target.value) })} /></label>
            <label className="block text-xs text-slate-500">Bảo trì<select className={input} value={edit.maintenance_status} onChange={(e) => setEdit({ ...edit, maintenance_status: e.target.value })}>{["OK", "MAINTENANCE", "DOWN"].map((s) => <option key={s}>{s}</option>)}</select></label>
            <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={!!edit.is_bottleneck} onChange={(e) => setEdit({ ...edit, is_bottleneck: e.target.checked })} /> Nút thắt của chuyền</label>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setEdit(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={saveMach} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">Lưu</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Lao động
function LaborTab() {
  const [rows, setRows] = useState<{ factory_code: string; line: string; day: string; present: number; total: number }[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/planning/resources/labor").then((r) => setRows(r.data)).catch((e) => setErr(errorMessage(e)));
  }, []);
  const byF = useMemo(() => {
    const m = new Map<string, typeof rows>();
    rows.forEach((r) => m.set(r.factory_code, [...(m.get(r.factory_code) ?? []), r]));
    return [...m.entries()].sort();
  }, [rows]);
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">Lao động có mặt theo chuyền ở lần đồng bộ gần nhất (eGMF). Recheck cảnh báo LABOR_SHORTAGE khi WORKER của dòng kế hoạch lớn hơn số người có mặt của chuyền.</p>
      {err && <p className="text-sm text-red-600">{err}</p>}
      {byF.length === 0 && <p className="text-sm text-slate-400">Chưa có dữ liệu lao động — đồng bộ eGMF ở Quản trị → Sync Log.</p>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {byF.map(([xn, lines]) => (
          <section key={xn} className="rounded-2xl border border-slate-200 bg-white p-4">
            <h3 className="text-sm font-bold text-slate-900">{xn} · {num(lines.reduce((s, l) => s + l.present, 0))} có mặt / {num(lines.reduce((s, l) => s + l.total, 0))} tổng</h3>
            <table className="mt-2 w-full text-left text-xs">
              <thead><tr className="text-slate-400"><th className="py-1">Chuyền</th><th className="text-right">Có mặt</th><th className="text-right">Tổng</th><th className="text-right">Ngày</th></tr></thead>
              <tbody>{lines.map((l) => <tr key={l.line} className="border-t border-slate-50"><td className="py-1">{l.line}</td><td className="text-right font-semibold">{l.present}</td><td className="text-right">{l.total}</td><td className="text-right text-slate-400">{dateVi(l.day)}</td></tr>)}</tbody>
            </table>
          </section>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Lịch giải phóng nguồn lực
interface RelCell { date: string; labor: number; machine: number }
interface RelData { week_start: string; days: string[]; note: string; factories: { factory: string; totals: RelCell[]; lines: { line: string; days: RelCell[] }[] }[] }

function ReleaseTab() {
  const [versions, setVersions] = useState<PlanVersion[]>([]);
  const [vid, setVid] = useState<number | null>(null);
  const [anchor, setAnchor] = useState(() => new Date());
  const [data, setData] = useState<RelData | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [err, setErr] = useState("");
  const range = weekRange(anchor);
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

  useEffect(() => {
    api.get<PlanVersion[]>("/planning/versions").then((r) => {
      setVersions(r.data);
      setVid((cur) => cur ?? r.data.find((v) => v.status === "ISSUED")?.id ?? r.data[0]?.id ?? null);
    }).catch((e) => setErr(errorMessage(e)));
  }, []);
  useEffect(() => {
    if (!vid) return;
    setErr("");
    api.get<RelData>("/planning/resources/release", { params: { version_id: vid, week_start: iso(range.start) } }).then((r) => setData(r.data)).catch((e) => setErr(errorMessage(e)));
  }, [vid, anchor]); // eslint-disable-line react-hooks/exhaustive-deps

  const w = isoWeek(range.start);
  const shiftWeek = (n: number) => setAnchor((a) => new Date(a.getFullYear(), a.getMonth(), a.getDate() + 7 * n));
  const toggle = (xn: string) => setOpen((cur) => { const n = new Set(cur); n.has(xn) ? n.delete(xn) : n.add(xn); return n; });
  const dayLabel = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("vi-VN", { weekday: "short", day: "2-digit", month: "2-digit" });
  const cell = (v: number) => (v > 0 ? <b>{num(v)}</b> : <span className="text-slate-400">0</span>);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select value={vid ?? ""} onChange={(e) => setVid(Number(e.target.value))} className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="Phiên bản">{versions.map((v) => <option key={v.id} value={v.id}>{v.code} · {v.status}</option>)}</select>
        <button onClick={() => shiftWeek(-1)} className="rounded-md border border-slate-300 px-2.5 py-1 text-xs" aria-label="Tuần trước">◀</button>
        <span className="rounded-lg bg-indigo-500/20 px-3 py-1 text-sm font-bold" data-testid="release-week">Tuần {w.week}/{w.year}</span>
        <button onClick={() => shiftWeek(1)} className="rounded-md border border-slate-300 px-2.5 py-1 text-xs" aria-label="Tuần sau">▶</button>
        <button onClick={() => setAnchor(new Date())} className="rounded-md border border-slate-300 px-2.5 py-1 text-xs">Tuần này</button>
        <span className="text-xs text-slate-500">{range.start.toLocaleDateString("vi-VN")} – {range.end.toLocaleDateString("vi-VN")}</span>
      </div>
      {err && <p className="text-sm text-red-600">{err}</p>}
      {data && (
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full min-w-[900px] border-collapse text-center text-sm" data-testid="release-table">
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
                <th rowSpan={2} className="px-4 py-2 text-left">XN / Chuyền</th>
                {data.days.map((d) => <th key={d} colSpan={2} className="border-l border-slate-100 py-2">{dayLabel(d)}</th>)}
              </tr>
              <tr className="border-b border-slate-100 text-[10px] uppercase text-slate-400">
                {data.days.flatMap((d) => [<th key={d + "l"} className="border-l border-slate-100 py-1">Lao động</th>, <th key={d + "m"} className="py-1">Máy</th>])}
              </tr>
            </thead>
            <tbody>
              {data.factories.length === 0 && <tr><td colSpan={15} className="py-8 text-slate-400">Không có dòng kế hoạch nào đang chạy quanh tuần này.</td></tr>}
              {data.factories.map((f) => (
                <FragmentRows key={f.factory} f={f} open={open.has(f.factory)} onToggle={() => toggle(f.factory)} cell={cell} />
              ))}
            </tbody>
          </table>
          <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-400">{data.note}</p>
        </div>
      )}
    </div>
  );
}

function FragmentRows({ f, open, onToggle, cell }: { f: RelData["factories"][number]; open: boolean; onToggle: () => void; cell: (v: number) => React.ReactNode }) {
  return (
    <>
      <tr className="cursor-pointer border-b border-slate-100 bg-slate-500/10 font-semibold" onClick={onToggle} data-testid={`rel-${f.factory}`}>
        <td className="px-4 py-2 text-left">{open ? "▼" : "▶"} {f.factory} <span className="text-xs font-normal text-slate-400">{f.lines.length} chuyền</span></td>
        {f.totals.flatMap((t) => [<td key={t.date + "l"} className="border-l border-slate-100">{cell(t.labor)}</td>, <td key={t.date + "m"}>{cell(t.machine)}</td>])}
      </tr>
      {open && f.lines.map((l) => (
        <tr key={l.line} className="border-b border-slate-50">
          <td className="py-1.5 pl-9 text-left text-slate-600">Chuyền {l.line}</td>
          {l.days.flatMap((t) => [<td key={t.date + "l"} className="border-l border-slate-50">{cell(t.labor)}</td>, <td key={t.date + "m"}>{cell(t.machine)}</td>])}
        </tr>
      ))}
    </>
  );
}

export default function Resources() {
  const { section } = useParams();
  const { can } = useAuth();
  const current = SECTIONS.find((s) => s.key === section);
  if (!current) return <Navigate to="/planning/resources/capacity" replace />;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Năng suất & nguồn lực</h1>
        <p className="text-xs text-slate-500">Capacity Definition, máy móc, lao động khả dụng và lịch giải phóng nguồn lực — nền cho kiểm tra khả thi khi Recheck.</p>
      </div>
      <nav className="flex gap-1 border-b border-slate-200">
        {SECTIONS.map((s) => (
          <NavLink key={s.key} to={`/planning/resources/${s.key}`} className={({ isActive }) => `-mb-px border-b-2 px-4 py-2 text-sm font-medium ${isActive ? "border-brand text-brand" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{s.label}</NavLink>
        ))}
      </nav>
      {current.key === "capacity" && <CapacityTab canManage={can("resource.manage")} />}
      {current.key === "machines" && <MachinesTab canManage={can("resource.manage")} />}
      {current.key === "labor" && <LaborTab />}
      {current.key === "release" && <ReleaseTab />}
    </div>
  );
}
