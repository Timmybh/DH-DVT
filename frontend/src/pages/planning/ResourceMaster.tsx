import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { dateVi, num } from "../../lib/format";
import StyleOutputPanel from "./StyleOutputPanel";

const input = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm";
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400 whitespace-nowrap";
const btn = "rounded-full border border-slate-300 px-3 py-1 text-xs";
const primary = "rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-40";
const XNS = ["XN1", "XN2", "XN3"];
const RES = "/planning/resources";

type Msg = { ok: boolean; text: string } | null;
const Notice = ({ msg }: { msg: Msg }) => (msg ? <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p> : null);

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-6 text-slate-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between">
          <h3 className="text-lg font-bold">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Đóng">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}
const Field = ({ label, children }: { label: string; children: React.ReactNode }) => <label className="block text-xs text-slate-500">{label}{children}</label>;
const numOrNull = (v: string) => (v === "" ? null : Number(v));

/** Chạy một thao tác rồi báo kết quả / lỗi. */
function useAct(reload: () => Promise<unknown>) {
  const [msg, setMsg] = useState<Msg>(null);
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      await reload();
      return true;
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
      return false;
    }
  };
  return { msg, setMsg, act };
}

// ================================================================ MÁY — cấp 1: Danh mục loại máy
interface MType { code: string; name: string; source: string; model: string; machine_group: string; process: string; nominal_output_per_day: number | null; default_efficiency: number | null; changeover_minutes: number | null; is_bottleneck_capable: boolean; effective_from: string | null; effective_to: string | null; status: string; note: string }

export function MachineTypesPanel({ canManage }: { canManage: boolean }) {
  const [rows, setRows] = useState<MType[]>([]);
  const [edit, setEdit] = useState<(Partial<MType> & { isNew?: boolean }) | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const load = useCallback(async () => setRows((await api.get<MType[]>(`${RES}/machine-types`, { params: { all: true } })).data), []);
  const { msg, setMsg, act } = useAct(load);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const save = async () => {
    if (!edit) return;
    const body = { name: edit.name ?? "", model: edit.model ?? "", machine_group: edit.machine_group ?? "", process: edit.process ?? "", nominal_output_per_day: edit.nominal_output_per_day ?? null, default_efficiency: edit.default_efficiency ?? null,
      changeover_minutes: edit.changeover_minutes ?? null, is_bottleneck_capable: !!edit.is_bottleneck_capable, effective_from: edit.effective_from || null, effective_to: edit.effective_to || null, note: edit.note ?? "" };
    const ok = await act(() => (edit.isNew ? api.post(`${RES}/machine-types`, { ...body, code: edit.code }) : api.put(`${RES}/machine-types/${edit.code}`, body)), "Đã lưu loại máy.");
    if (ok) setEdit(null);
  };
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">Danh mục loại máy dùng chung toàn công ty. Hiện khai báo thủ công (chưa đồng bộ từ ERP; các loại máy đã đồng bộ trước đây vẫn được giữ). Không xóa — chỉ Ngưng áp dụng.</p>
      <Notice msg={msg} />
      <div className="flex"><span className="flex-1" />{canManage && <button onClick={() => setEdit({ isNew: true, code: "", name: "", is_bottleneck_capable: false })} className={primary} data-testid="mtype-add">+ Thêm loại máy</button>}</div>
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full min-w-[720px] text-sm" data-testid="mtype-table">
          <thead><tr><th className={th}>Mã</th><th className={th}>Tên</th><th className={th}>Model</th><th className={th}>Nhóm máy</th><th className={th}>Công đoạn</th><th className={`${th} text-right`}>Công suất/ngày</th><th className={`${th} text-right`}>OEE mặc định</th><th className={th}>Nguồn</th><th className={th}>Trạng thái</th><th className={th} /></tr></thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.code} onClick={() => setSelected(t.code)} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-500/5 ${selected === t.code ? "bg-indigo-500/10" : ""} ${t.status === "INACTIVE" ? "opacity-50" : ""}`} data-testid={`mtype-${t.code}`}>
                <td className="px-3 py-1.5 font-mono text-xs">{t.code}</td><td className="px-3">{t.name}</td><td className="px-3">{t.model}</td><td className="px-3">{t.machine_group}</td><td className="px-3">{t.process}</td>
                <td className="px-3 text-right">{t.nominal_output_per_day ? num(t.nominal_output_per_day) : "—"}</td><td className="px-3 text-right">{t.default_efficiency ?? "—"}</td>
                <td className="px-3 text-xs text-slate-400">{t.source === "EGMF" ? "ERP" : "nhập tay"}</td>
                <td className="px-3"><span className={`pg-chip ${t.status === "ACTIVE" ? "pg-ok" : "bg-slate-500/20 text-slate-500"}`}>{t.status === "ACTIVE" ? "Đang dùng" : "Ngưng"}</span></td>
                <td className="whitespace-nowrap px-3 text-right text-xs" onClick={(e) => e.stopPropagation()}>{canManage && <>
                  <button onClick={() => setEdit(t)} className="text-brand hover:underline">Sửa</button>
                  <button onClick={() => act(() => api.post(`${RES}/machine-types/${t.code}/${t.status === "ACTIVE" ? "deactivate" : "activate"}`), t.status === "ACTIVE" ? "Đã ngưng loại máy." : "Đã áp dụng lại.")} className="ml-3 text-slate-500 hover:underline">{t.status === "ACTIVE" ? "Ngưng" : "Áp dụng lại"}</button></>}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={10} className="py-6 text-center text-slate-400">Chưa có loại máy — thêm tay.</td></tr>}
          </tbody>
        </table>
      </div>
      <StyleOutputPanel machineType={selected} machineName={rows.find((t) => t.code === selected)?.name ?? ""} canManage={canManage} />
      </div>
      {edit && (
        <Modal title={edit.isNew ? "Thêm loại máy" : `Sửa loại máy ${edit.code}`} onClose={() => setEdit(null)}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Mã loại máy"><input className={input} disabled={!edit.isNew} value={edit.code ?? ""} onChange={(e) => setEdit({ ...edit, code: e.target.value.toUpperCase() })} /></Field>
            <Field label="Tên"><input className={input} value={edit.name ?? ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Model"><input className={input} value={edit.model ?? ""} onChange={(e) => setEdit({ ...edit, model: e.target.value })} /></Field>
            <Field label="Nhóm máy"><input className={input} value={edit.machine_group ?? ""} onChange={(e) => setEdit({ ...edit, machine_group: e.target.value })} /></Field>
            <Field label="Công đoạn"><input className={input} value={edit.process ?? ""} onChange={(e) => setEdit({ ...edit, process: e.target.value })} /></Field>
            <Field label="Công suất danh định (pcs/ngày)"><input type="number" className={input} value={edit.nominal_output_per_day ?? ""} onChange={(e) => setEdit({ ...edit, nominal_output_per_day: numOrNull(e.target.value) })} /></Field>
            <Field label="OEE mặc định (0–1)"><input type="number" step="0.05" className={input} value={edit.default_efficiency ?? ""} onChange={(e) => setEdit({ ...edit, default_efficiency: numOrNull(e.target.value) })} /></Field>
            <Field label="Thời gian đổi mẫu (phút)"><input type="number" className={input} value={edit.changeover_minutes ?? ""} onChange={(e) => setEdit({ ...edit, changeover_minutes: numOrNull(e.target.value) })} /></Field>
            <Field label="Hiệu lực từ"><input type="date" className={input} value={edit.effective_from ?? ""} onChange={(e) => setEdit({ ...edit, effective_from: e.target.value })} /></Field>
            <Field label="Hiệu lực đến"><input type="date" className={input} value={edit.effective_to ?? ""} onChange={(e) => setEdit({ ...edit, effective_to: e.target.value })} /></Field>
            <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.is_bottleneck_capable} onChange={(e) => setEdit({ ...edit, is_bottleneck_capable: e.target.checked })} /> Có thể là nút thắt</label>
            <Field label="Ghi chú"><input className={`${input} col-span-2`} value={edit.note ?? ""} onChange={(e) => setEdit({ ...edit, note: e.target.value })} /></Field>
          </div>
          <div className="mt-5 flex justify-end gap-2"><button onClick={() => setEdit(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button><button onClick={save} disabled={!edit.code} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Lưu</button></div>
        </Modal>
      )}
    </div>
  );
}

// ================================================================ MÁY — cấp 3: đăng ký mượn máy + lịch bảo trì
interface Share { id: number; machine_type: string; from_factory: string; from_line: string; to_factory: string; to_line: string; quantity: number; date_from: string; date_to: string; reason: string; status: string }
interface Pool { id: number; factory_code: string; machine_type: string; quantity: number; lines: string[]; effective_from: string | null; effective_to: string | null; note: string; status: string }
interface Maint { id: number; factory_code: string; line: string; machine_type: string; quantity: number; date_from: string; date_to: string; kind: string; reason: string; status: string }
const KIND: Record<string, string> = { PLANNED: "Theo kế hoạch", BREAKDOWN: "Hỏng đột xuất", OTHER: "Khác" };

export function MachineSharingMaintenancePanel({ canManage }: { canManage: boolean }) {
  const [factory, setFactory] = useState("XN1");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [inactive, setInactive] = useState(false);
  const [shares, setShares] = useState<Share[]>([]);
  const [maints, setMaints] = useState<Maint[]>([]);
  const [types, setTypes] = useState<MType[]>([]);
  const [eS, setES] = useState<Partial<Share> | null>(null);
  const [eM, setEM] = useState<Partial<Maint> | null>(null);
  const [pools, setPools] = useState<Pool[]>([]);
  const [eP, setEP] = useState<Partial<Pool> | null>(null);
  const [lineOptions, setLineOptions] = useState<string[]>([]);
  const load = useCallback(async () => {
    const p = { factory: factory || undefined, include_inactive: inactive };
    const [s, m, t, pl, cap] = await Promise.all([api.get<Share[]>(`${RES}/machine-sharing`, { params: p }), api.get<Maint[]>(`${RES}/machine-maintenance`, { params: p }), api.get<MType[]>(`${RES}/machine-types`),
      api.get<Pool[]>(`${RES}/machine-shared`, { params: p }), api.get<{ line: string }[]>(`${RES}/machine-capacity`, { params: { factory } })]);
    setShares(s.data); setMaints(m.data); setTypes(t.data); setPools(pl.data);
    setLineOptions([...new Set(cap.data.map((c) => c.line))].sort((a, b) => a.padStart(6, "0").localeCompare(b.padStart(6, "0"))));
  }, [factory, inactive]);
  const { msg, setMsg, act } = useAct(load);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const toggle = (kind: "machine-sharing" | "machine-maintenance" | "machine-shared", id: number, active: boolean) => {
    const reason = active ? "" : window.prompt("Lý do ngưng áp dụng?") ?? "";
    if (!active && reason.trim().length < 1) return;
    void act(() => api.post(`${RES}/${kind}/${id}/${active ? "activate" : "deactivate"}`, { reason }), active ? "Đã áp dụng lại." : "Đã ngưng áp dụng.");
  };
  const natLine = (x: string) => x.padStart(6, "0");
  const toggleGroup = (k: string) => setCollapsed((cur) => { const n = new Set(cur); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  // Đăng ký mượn máy: chuyền của XN đang chọn ở phía cho mượn và/hoặc phía nhận
  const shareGroups = useMemo(() => {
    const m = new Map<string, { key: string; line: string; items: { r: Share; dir: "LEND" | "BORROW" }[] }>();
    const put = (line: string, r: Share, dir: "LEND" | "BORROW") => { const key = `s-${line}`; const g = m.get(key) ?? { key, line, items: [] }; g.items.push({ r, dir }); m.set(key, g); };
    shares.forEach((r) => { if (r.from_factory === factory) put(r.from_line, r, "LEND"); if (r.to_factory === factory) put(r.to_line, r, "BORROW"); });
    return [...m.values()].sort((a, b) => natLine(a.line).localeCompare(natLine(b.line)));
  }, [shares, factory]);
  const maintGroups = useMemo(() => {
    const m = new Map<string, { key: string; line: string; items: Maint[] }>();
    maints.forEach((r) => { const key = `m-${r.line}`; const g = m.get(key) ?? { key, line: r.line, items: [] }; g.items.push(r); m.set(key, g); });
    return [...m.values()].sort((a, b) => natLine(a.line).localeCompare(natLine(b.line)));
  }, [maints]);
  const typeList = <datalist id="mtype-list">{types.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}</datalist>;
  return (
    <div className="space-y-6">
      <p className="text-xs text-slate-500">Đăng ký mượn máy giữa các xí nghiệp/chuyền và lịch bảo trì từng xí nghiệp. Trong khoảng ngày đăng ký, số máy sẵn sàng của chuyền được cộng/trừ tương ứng khi Recheck (theo ngày bắt đầu sản xuất của dòng). Không xóa — chỉ Ngưng áp dụng.</p>
      <Notice msg={msg} />
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="tablist" aria-label="Xí nghiệp">
          {XNS.map((f) => <button key={f} role="tab" aria-selected={factory === f} onClick={() => setFactory(f)} className={`rounded-full border px-4 py-1.5 text-xs font-semibold ${factory === f ? "border-brand bg-indigo-500/20 text-brand" : "border-slate-200 text-slate-500"}`} data-testid={`share-xn-${f}`}>{f}</button>)}
        </div>
        <label className="flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} /> Hiện cả đã ngưng</label>
        <span className="flex-1" />
        <button onClick={() => setCollapsed(collapsed.size ? new Set() : new Set([...shareGroups, ...maintGroups].map((g) => g.key)))} className={btn}>{collapsed.size ? "Mở tất cả" : "Thu gọn tất cả"}</button>
      </div>
      {typeList}

      <section className="space-y-2">
        <div className="flex items-center gap-2"><h2 className="text-sm font-bold text-slate-900">Đăng ký mượn máy máy — {factory}</h2><span className="flex-1" />
          {canManage && <button onClick={() => setES({ machine_type: "", from_factory: factory, from_line: "", to_factory: XNS.find((x) => x !== factory) ?? "XN2", to_line: "", quantity: 1, date_from: "", date_to: "", reason: "" })} className={primary} data-testid="share-add">+ Đăng ký mượn</button>}</div>
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full min-w-[820px] text-sm" data-testid="share-table">
            <thead><tr><th className={th}>Chuyền / loại máy</th><th className={th}>Hướng</th><th className={th}>Bên kia (XN/chuyền)</th><th className={`${th} text-right`}>SL</th><th className={th}>Từ ngày</th><th className={th}>Đến ngày</th><th className={th}>Lý do</th><th className={th} /></tr></thead>
            <tbody>
              {shareGroups.map((g) => {
                const isOpen = !collapsed.has(g.key);
                return [
                  <tr key={g.key} className="cursor-pointer border-t border-slate-100 bg-slate-500/5 hover:bg-slate-500/10" onClick={() => toggleGroup(g.key)}>
                    <td className="px-3 py-1.5 font-semibold" colSpan={3}><span className="mr-1 text-slate-400">{isOpen ? "▾" : "▸"}</span>{g.line ? `Chuyền ${g.line}` : "Chưa gắn chuyền"}<span className="ml-2 text-xs font-normal text-slate-400">{g.items.length} đăng ký</span></td>
                    <td className="px-3 text-right font-semibold">{g.items.reduce((t, e) => t + (e.dir === "LEND" ? -e.r.quantity : e.r.quantity), 0)}</td><td colSpan={4} className="px-3 text-xs text-slate-400">ròng (nhận − cho mượn)</td>
                  </tr>,
                  ...(isOpen ? g.items.map((e) => (
                    <tr key={`${g.key}-${e.r.id}-${e.dir}`} className={`border-t border-slate-50 text-[13px] ${e.r.status === "INACTIVE" ? "opacity-50" : ""}`}>
                      <td className="py-1 pl-10 font-mono text-xs">{e.r.machine_type}</td><td className="px-3 text-xs">{e.dir === "LEND" ? "Cho mượn →" : "← Mượn từ"}</td>
                      <td className="px-3">{e.dir === "LEND" ? `${e.r.to_factory}${e.r.to_line ? `/${e.r.to_line}` : ""}` : `${e.r.from_factory}${e.r.from_line ? `/${e.r.from_line}` : ""}`}</td>
                      <td className="px-3 text-right font-semibold">{e.r.quantity}</td><td className="px-3">{dateVi(e.r.date_from)}</td><td className="px-3">{dateVi(e.r.date_to)}</td>
                      <td className="max-w-[220px] truncate px-3 text-xs text-slate-500" title={e.r.reason}>{e.r.reason}</td>
                      <td className="px-3 text-right text-xs">{canManage && <button onClick={() => toggle("machine-sharing", e.r.id, e.r.status === "INACTIVE")} className="text-slate-500 hover:underline">{e.r.status === "INACTIVE" ? "Áp dụng lại" : "Ngưng áp dụng"}</button>}</td>
                    </tr>
                  )) : []),
                ];
              })}
              {shares.length === 0 && <tr><td colSpan={8} className="py-5 text-center text-slate-400">{factory} chưa có đăng ký mượn máy.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-2"><h2 className="text-sm font-bold text-slate-900">Đăng ký dùng chung nhiều chuyền — {factory}</h2><span className="flex-1" />
          {canManage && <button onClick={() => setEP({ factory_code: factory, machine_type: "", quantity: 1, lines: [], note: "" })} className={primary} data-testid="pool-add">+ Đăng ký dùng chung</button>}</div>
        <p className="text-xs text-slate-500">Máy không thuộc riêng chuyền nào mà nhiều chuyền cùng dùng (mỗi chuyền trong danh sách được dùng tối đa số máy đã đăng ký).</p>
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full min-w-[720px] text-sm" data-testid="pool-table">
            <thead><tr><th className={th}>Loại máy</th><th className={`${th} text-right`}>SL</th><th className={th}>Các chuyền dùng chung</th><th className={th}>Hiệu lực</th><th className={th}>Ghi chú</th><th className={th} /></tr></thead>
            <tbody>
              {pools.map((r) => (
                <tr key={r.id} className={`border-t border-slate-100 ${r.status === "INACTIVE" ? "opacity-50" : ""}`}>
                  <td className="px-3 py-1.5 font-mono text-xs">{r.machine_type}</td><td className="px-3 text-right font-semibold">{r.quantity}</td>
                  <td className="px-3"><span className="flex flex-wrap gap-1">{[...r.lines].sort((a, b) => natLine(a).localeCompare(natLine(b))).map((l) => <span key={l} className="pg-chip bg-slate-500/20 text-slate-600">Chuyền {l}</span>)}</span></td>
                  <td className="whitespace-nowrap px-3 text-xs text-slate-500">{r.effective_from ? dateVi(r.effective_from) : "—"}{r.effective_to ? ` → ${dateVi(r.effective_to)}` : ""}</td>
                  <td className="max-w-[200px] truncate px-3 text-xs text-slate-500" title={r.note}>{r.note}</td>
                  <td className="px-3 text-right text-xs">{canManage && <button onClick={() => toggle("machine-shared", r.id, r.status === "INACTIVE")} className="text-slate-500 hover:underline">{r.status === "INACTIVE" ? "Áp dụng lại" : "Ngưng áp dụng"}</button>}</td>
                </tr>
              ))}
              {pools.length === 0 && <tr><td colSpan={6} className="py-5 text-center text-slate-400">{factory} chưa có đăng ký dùng chung.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-2"><h2 className="text-sm font-bold text-slate-900">Lịch bảo trì máy — {factory}</h2><span className="flex-1" />
          {canManage && <button onClick={() => setEM({ factory_code: factory, line: "", machine_type: "", quantity: 1, date_from: "", date_to: "", kind: "PLANNED", reason: "" })} className={primary} data-testid="maint-add">+ Thêm lịch bảo trì</button>}</div>
        <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
          <table className="w-full min-w-[780px] text-sm" data-testid="maint-table">
            <thead><tr><th className={th}>Chuyền / loại máy</th><th className={`${th} text-right`}>SL</th><th className={th}>Từ ngày</th><th className={th}>Đến ngày</th><th className={th}>Loại</th><th className={th}>Lý do</th><th className={th} /></tr></thead>
            <tbody>
              {maintGroups.map((g) => {
                const isOpen = !collapsed.has(g.key);
                return [
                  <tr key={g.key} className="cursor-pointer border-t border-slate-100 bg-slate-500/5 hover:bg-slate-500/10" onClick={() => toggleGroup(g.key)}>
                    <td className="px-3 py-1.5 font-semibold"><span className="mr-1 text-slate-400">{isOpen ? "▾" : "▸"}</span>Chuyền {g.line}<span className="ml-2 text-xs font-normal text-slate-400">{g.items.length} lịch</span></td>
                    <td className="px-3 text-right font-semibold">{g.items.reduce((t, r) => t + r.quantity, 0)}</td><td colSpan={5} />
                  </tr>,
                  ...(isOpen ? g.items.map((r) => (
                    <tr key={r.id} className={`border-t border-slate-50 text-[13px] ${r.status === "INACTIVE" ? "opacity-50" : ""}`}>
                      <td className="py-1 pl-10 font-mono text-xs">{r.machine_type}</td><td className="px-3 text-right font-semibold">{r.quantity}</td>
                      <td className="px-3">{dateVi(r.date_from)}</td><td className="px-3">{dateVi(r.date_to)}</td><td className="px-3 text-xs">{KIND[r.kind] ?? r.kind}</td>
                      <td className="max-w-[220px] truncate px-3 text-xs text-slate-500" title={r.reason}>{r.reason}</td>
                      <td className="px-3 text-right text-xs">{canManage && <button onClick={() => toggle("machine-maintenance", r.id, r.status === "INACTIVE")} className="text-slate-500 hover:underline">{r.status === "INACTIVE" ? "Áp dụng lại" : "Ngưng áp dụng"}</button>}</td>
                    </tr>
                  )) : []),
                ];
              })}
              {maints.length === 0 && <tr><td colSpan={7} className="py-5 text-center text-slate-400">{factory} chưa có lịch bảo trì.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {eP && (
        <Modal title="Đăng ký dùng chung nhiều chuyền" onClose={() => setEP(null)}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Loại máy"><input list="mtype-list" className={input} value={eP.machine_type ?? ""} onChange={(e) => setEP({ ...eP, machine_type: e.target.value.toUpperCase() })} data-testid="pool-type" /></Field>
            <Field label="Số lượng máy dùng chung"><input type="number" min={1} className={input} value={eP.quantity ?? 1} onChange={(e) => setEP({ ...eP, quantity: Number(e.target.value) })} /></Field>
            <Field label="Từ ngày (không bắt buộc)"><input type="date" className={input} value={eP.effective_from ?? ""} onChange={(e) => setEP({ ...eP, effective_from: e.target.value })} /></Field>
            <Field label="Đến ngày (không bắt buộc)"><input type="date" className={input} value={eP.effective_to ?? ""} onChange={(e) => setEP({ ...eP, effective_to: e.target.value })} /></Field>
          </div>
          <p className="mt-3 text-xs text-slate-500">Chọn các chuyền của {eP.factory_code} cùng dùng (từ 2 chuyền):</p>
          <div className="mt-1 flex flex-wrap gap-1.5" data-testid="pool-lines">
            {(lineOptions.length ? lineOptions : []).map((l) => {
              const on = (eP.lines ?? []).includes(l);
              return <button key={l} type="button" onClick={() => setEP({ ...eP, lines: on ? (eP.lines ?? []).filter((x) => x !== l) : [...(eP.lines ?? []), l] })} aria-pressed={on} className={`rounded-full border px-3 py-1 text-xs font-semibold ${on ? "border-brand bg-indigo-500/20 text-brand" : "border-slate-200 text-slate-500"}`} data-testid={`pool-line-${l}`}>Chuyền {l}</button>;
            })}
            {lineOptions.length === 0 && <span className="text-xs text-slate-400">Chưa có chuyền — khai báo phân bổ máy trước.</span>}
          </div>
          <div className="mt-3"><Field label="Ghi chú"><input className={input} value={eP.note ?? ""} onChange={(e) => setEP({ ...eP, note: e.target.value })} /></Field></div>
          <div className="mt-5 flex justify-end gap-2"><button onClick={() => setEP(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button disabled={!eP.machine_type || (eP.lines ?? []).length < 2} onClick={async () => { if (await act(() => api.post(`${RES}/machine-shared`, { ...eP, effective_from: eP.effective_from || null, effective_to: eP.effective_to || null }), "Đã đăng ký dùng chung.")) setEP(null); }} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="pool-save">Lưu</button></div>
        </Modal>
      )}
      {eS && (
        <Modal title="Đăng ký mượn máy máy" onClose={() => setES(null)}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Loại máy"><input list="mtype-list" className={input} value={eS.machine_type ?? ""} onChange={(e) => setES({ ...eS, machine_type: e.target.value.toUpperCase() })} /></Field>
            <Field label="Số lượng"><input type="number" min={1} className={input} value={eS.quantity ?? 1} onChange={(e) => setES({ ...eS, quantity: Number(e.target.value) })} /></Field>
            <Field label="XN cho mượn"><select className={input} value={eS.from_factory} onChange={(e) => setES({ ...eS, from_factory: e.target.value })}>{XNS.map((f) => <option key={f}>{f}</option>)}</select></Field>
            <Field label="Chuyền cho mượn (để trừ máy)"><input className={input} value={eS.from_line ?? ""} onChange={(e) => setES({ ...eS, from_line: e.target.value })} /></Field>
            <Field label="XN mượn (nhận máy)"><select className={input} value={eS.to_factory} onChange={(e) => setES({ ...eS, to_factory: e.target.value })}>{XNS.map((f) => <option key={f}>{f}</option>)}</select></Field>
            <Field label="Chuyền mượn (để cộng máy)"><input className={input} value={eS.to_line ?? ""} onChange={(e) => setES({ ...eS, to_line: e.target.value })} /></Field>
            <Field label="Từ ngày"><input type="date" className={input} value={eS.date_from ?? ""} onChange={(e) => setES({ ...eS, date_from: e.target.value })} /></Field>
            <Field label="Đến ngày"><input type="date" className={input} value={eS.date_to ?? ""} onChange={(e) => setES({ ...eS, date_to: e.target.value })} /></Field>
            <div className="col-span-2"><Field label="Lý do"><input className={input} value={eS.reason ?? ""} onChange={(e) => setES({ ...eS, reason: e.target.value })} /></Field></div>
          </div>
          <div className="mt-5 flex justify-end gap-2"><button onClick={() => setES(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={async () => { if (await act(() => api.post(`${RES}/machine-sharing`, eS), "Đã đăng ký mượn máy.")) setES(null); }} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">Lưu</button></div>
        </Modal>
      )}
      {eM && (
        <Modal title="Lịch bảo trì máy" onClose={() => setEM(null)}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Xí nghiệp"><select className={input} value={eM.factory_code} onChange={(e) => setEM({ ...eM, factory_code: e.target.value })}>{XNS.map((f) => <option key={f}>{f}</option>)}</select></Field>
            <Field label="Chuyền"><input className={input} value={eM.line ?? ""} onChange={(e) => setEM({ ...eM, line: e.target.value })} /></Field>
            <Field label="Loại máy"><input list="mtype-list" className={input} value={eM.machine_type ?? ""} onChange={(e) => setEM({ ...eM, machine_type: e.target.value.toUpperCase() })} /></Field>
            <Field label="Số máy bảo trì"><input type="number" min={1} className={input} value={eM.quantity ?? 1} onChange={(e) => setEM({ ...eM, quantity: Number(e.target.value) })} /></Field>
            <Field label="Từ ngày"><input type="date" className={input} value={eM.date_from ?? ""} onChange={(e) => setEM({ ...eM, date_from: e.target.value })} /></Field>
            <Field label="Đến ngày"><input type="date" className={input} value={eM.date_to ?? ""} onChange={(e) => setEM({ ...eM, date_to: e.target.value })} /></Field>
            <Field label="Loại bảo trì"><select className={input} value={eM.kind} onChange={(e) => setEM({ ...eM, kind: e.target.value })}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            <Field label="Lý do"><input className={input} value={eM.reason ?? ""} onChange={(e) => setEM({ ...eM, reason: e.target.value })} /></Field>
          </div>
          <div className="mt-5 flex justify-end gap-2"><button onClick={() => setEM(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={async () => { if (await act(() => api.post(`${RES}/machine-maintenance`, eM), "Đã thêm lịch bảo trì.")) setEM(null); }} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">Lưu</button></div>
        </Modal>
      )}
    </div>
  );
}

// ================================================================ LAO ĐỘNG — cấp 1: Danh mục bậc
interface Grade { id: number; grade: number; code: string; name: string; productivity_factor: number; effective_from: string | null; effective_to: string | null; status: string; note: string }

export function GradesPanel({ canManage }: { canManage: boolean }) {
  const [rows, setRows] = useState<Grade[]>([]);
  const [hist, setHist] = useState(false);
  const [edit, setEdit] = useState<{ grade: number; factor: string; from: string; note: string } | null>(null);
  const load = useCallback(async () => setRows((await api.get<Grade[]>(`${RES}/productivity-grades`, { params: { all: hist } })).data), [hist]);
  const { msg, setMsg, act } = useAct(load);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const today = new Date().toISOString().slice(0, 10);
  const today0 = (r: Grade) => r.status === "ACTIVE" && (!r.effective_from || r.effective_from <= today) && (!r.effective_to || r.effective_to >= today);
  const shown = hist ? rows : rows.filter(today0);
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">Danh mục bậc lao động (Productivity Grade 1–10) và hệ số năng suất. Đổi hệ số = tạo phiên bản mới có ngày hiệu lực, bản cũ được giữ lại. Bậc cao không được có hệ số thấp hơn bậc thấp. Không xóa.</p>
      <Notice msg={msg} />
      <label className="flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={hist} onChange={(e) => setHist(e.target.checked)} /> Hiện lịch sử hệ số</label>
      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full text-sm" data-testid="grade-table">
          <thead><tr><th className={th}>Bậc</th><th className={th}>Mã</th><th className={th}>Tên</th><th className={`${th} text-right`}>Hệ số</th><th className={th}>Hiệu lực từ</th><th className={th}>Đến</th><th className={th}>Trạng thái</th><th className={th} /></tr></thead>
          <tbody>
            {shown.map((g) => (
              <tr key={g.id} className={`border-t border-slate-100 ${g.status !== "ACTIVE" ? "opacity-50" : ""}`}>
                <td className="px-3 py-1.5 font-semibold">{g.grade}</td><td className="px-3 font-mono text-xs">{g.code}</td><td className="px-3">{g.name}</td>
                <td className="px-3 text-right font-semibold">{Math.round(g.productivity_factor * 1000) / 10}%</td><td className="px-3">{g.effective_from ? dateVi(g.effective_from) : "—"}</td><td className="px-3">{g.effective_to ? dateVi(g.effective_to) : "—"}</td>
                <td className="px-3"><span className={`pg-chip ${g.status === "ACTIVE" ? "pg-ok" : "bg-slate-500/20 text-slate-500"}`}>{g.status === "ACTIVE" ? "Đang dùng" : "Ngưng"}</span></td>
                <td className="whitespace-nowrap px-3 text-right text-xs">{canManage && <>
                  {today0(g) && <button onClick={() => setEdit({ grade: g.grade, factor: String(Math.round(g.productivity_factor * 1000) / 10), from: today, note: g.note })} className="text-brand hover:underline" data-testid={`grade-rev-${g.grade}`}>Đổi hệ số</button>}
                  <button onClick={() => act(() => api.post(`${RES}/productivity-grades/id/${g.id}/${g.status === "ACTIVE" ? "deactivate" : "activate"}`), "Đã cập nhật trạng thái.")} className="ml-3 text-slate-500 hover:underline">{g.status === "ACTIVE" ? "Ngưng" : "Áp dụng lại"}</button></>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edit && (
        <Modal title={`Đổi hệ số bậc ${edit.grade}`} onClose={() => setEdit(null)}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Hệ số mới (%)"><input type="number" className={input} value={edit.factor} onChange={(e) => setEdit({ ...edit, factor: e.target.value })} data-testid="grade-factor" /></Field>
            <Field label="Hiệu lực từ ngày"><input type="date" className={input} value={edit.from} onChange={(e) => setEdit({ ...edit, from: e.target.value })} /></Field>
          </div>
          <div className="mt-5 flex justify-end gap-2"><button onClick={() => setEdit(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={async () => { if (await act(() => api.post(`${RES}/productivity-grades/${edit.grade}/revise`, { productivity_factor: Number(edit.factor) / 100, effective_from: edit.from, note: edit.note }), "Đã tạo phiên bản hệ số mới.")) setEdit(null); }} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">Lưu</button></div>
        </Modal>
      )}
    </div>
  );
}

// ================================================================ LAO ĐỘNG — cấp 2: số lao động theo XN/chuyền và từng bậc
interface Comp { lines: { grade: number; factor: number | null; headcount: number; equivalent: number }[]; standard_labor: number; headcount: number; effective_equivalent: number; weighted_factor: number | null }
interface Std { id: number; factory_code: string; line: string; total_labor: number; effective_from: string; effective_to: string | null; status: string; version: number; note: string; composition: Comp }
type Draft = { id?: number; factory_code: string; line: string; effective_from: string; note: string; heads: Record<number, string> };

export function LaborStandardsPanel({ canManage }: { canManage: boolean }) {
  const [factory, setFactory] = useState("XN1");
  const [hist, setHist] = useState(false);
  const [openIds, setOpenIds] = useState<Set<number>>(new Set());
  const [rows, setRows] = useState<Std[]>([]);
  const [grades, setGrades] = useState<Grade[]>([]);
  const [d, setD] = useState<Draft | null>(null);
  const load = useCallback(async () => {
    const [s, g] = await Promise.all([api.get<Std[]>(`${RES}/labor-standards`, { params: { factory: factory || undefined, include_history: hist } }), api.get<Grade[]>(`${RES}/productivity-grades`)]);
    setRows(s.data); setGrades(g.data);
  }, [factory, hist]);
  const { msg, setMsg, act } = useAct(load);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load, setMsg]);
  const today = new Date().toISOString().slice(0, 10);
  const nat = (x: string) => x.padStart(6, "0");
  const sorted = [...rows].sort((a, b) => nat(a.line).localeCompare(nat(b.line)) || b.effective_from.localeCompare(a.effective_from));
  const sum = rows.filter((r) => r.status === "ACTIVE").reduce((t, r) => ({ total: t.total + r.composition.standard_labor, eq: t.eq + r.composition.effective_equivalent }), { total: 0, eq: 0 });
  const gradeNums = [...new Set(grades.map((g) => g.grade))].sort((a, b) => b - a);
  const factorOf = (n: number) => grades.filter((g) => g.grade === n && (!g.effective_from || g.effective_from <= (d?.effective_from || today))).sort((a, b) => (b.effective_from ?? "").localeCompare(a.effective_from ?? ""))[0]?.productivity_factor ?? 0;
  const total = d ? Object.values(d.heads).reduce((s, v) => s + (Number(v) || 0), 0) : 0;
  const equiv = d ? Object.entries(d.heads).reduce((s, [g, v]) => s + (Number(v) || 0) * factorOf(Number(g)), 0) : 0;
  const open = (s?: Std) => setD(s
    ? { id: s.id, factory_code: s.factory_code, line: s.line, effective_from: today > s.effective_from ? today : s.effective_from, note: s.note, heads: Object.fromEntries(s.composition.lines.map((l) => [l.grade, String(l.headcount)])) }
    : { factory_code: factory, line: "", effective_from: today, note: "", heads: {} });
  // Chuyền đã có cơ cấu đang áp dụng: không tạo mới (sẽ trùng) mà chuyển sang sửa, nạp sẵn số người hiện tại để bổ sung thêm bậc
  const existing = d && !d.id ? rows.find((r) => r.status === "ACTIVE" && r.factory_code === d.factory_code && r.line === d.line) : undefined;
  const editExisting = () => existing && open(existing);
  // Chọn/nhập chuyền đã có cơ cấu: nạp sẵn số người từng bậc để chỉnh (chuyền chưa có thì để trống)
  const pickLine = (line: string) => {
    if (!d || d.id) return;
    const ex = rows.find((r) => r.status === "ACTIVE" && r.factory_code === d.factory_code && r.line === line.trim());
    setD({ ...d, line, heads: ex ? Object.fromEntries(ex.composition.lines.map((l) => [l.grade, String(l.headcount)])) : d.heads });
  };
  const save = async () => {
    if (!d) return;
    const details = Object.entries(d.heads).filter(([, v]) => Number(v) > 0).map(([g, v]) => ({ grade: Number(g), headcount: Number(v) }));
    const body = { factory_code: d.factory_code, line: d.line, total_labor: total, effective_from: d.effective_from, note: d.note, details };
    const target = d.id ?? existing?.id;
    if (await act(() => (target ? api.post(`${RES}/labor-standards/${target}/revise`, body) : api.post(`${RES}/labor-standards`, body)), target ? "Đã cập nhật cơ cấu (tạo phiên bản mới)." : "Đã lưu cơ cấu lao động.")) setD(null);
  };
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">Số lao động theo từng xí nghiệp / chuyền và từng bậc. Hệ số TB của chuyền = trung bình gia quyền theo số người từng bậc. Không ghi đè: sửa = phiên bản mới có ngày hiệu lực. Chuyền để trống = áp cho cả xí nghiệp.</p>
      <Notice msg={msg} />
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="tablist" aria-label="Xí nghiệp">
          {XNS.map((f) => <button key={f} role="tab" aria-selected={factory === f} onClick={() => { setFactory(f); setOpenIds(new Set()); }} className={`rounded-full border px-4 py-1.5 text-xs font-semibold ${factory === f ? "border-brand bg-indigo-500/20 text-brand" : "border-slate-200 text-slate-500"}`} data-testid={`std-xn-${f}`}>{f}</button>)}
        </div>
        <span className="text-xs text-slate-500" data-testid="std-summary">{rows.filter((r) => r.status === "ACTIVE").length} chuyền · {num(sum.total)} người · hệ số TB {sum.total ? `${Math.round((sum.eq / sum.total) * 10000) / 100}%` : "—"}</span>
        <label className="flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={hist} onChange={(e) => setHist(e.target.checked)} /> Hiện lịch sử phiên bản</label>
        <span className="flex-1" />
        <button onClick={() => setOpenIds(openIds.size ? new Set() : new Set(sorted.map((r) => r.id)))} className={btn}>{openIds.size ? "Thu gọn tất cả" : "Mở tất cả"}</button>
        {canManage && <button onClick={() => open()} className={primary} data-testid="std-add">Khai báo LĐ</button>}
      </div>
      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full min-w-[720px] text-sm" data-testid="std-list">
          <thead><tr><th className={th}>Chuyền</th><th className={`${th} text-right`}>Tổng lao động</th><th className={`${th} text-right`}>Hệ số TB</th><th className={th}>Hiệu lực</th><th className={th} /></tr></thead>
          <tbody>
            {sorted.map((s) => {
              const isOpen = openIds.has(s.id);
              const c = s.composition;
              return [
                <tr key={s.id} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-500/5 ${s.status !== "ACTIVE" ? "opacity-60" : ""}`} onClick={() => setOpenIds((cur) => { const n = new Set(cur); if (n.has(s.id)) n.delete(s.id); else n.add(s.id); return n; })} data-testid={`std-${s.id}`}>
                  <td className="px-3 py-1.5 font-semibold"><span className="mr-1 text-slate-400">{isOpen ? "▾" : "▸"}</span>{s.line ? `Chuyền ${s.line}` : "Cả xí nghiệp"}{hist && <span className="ml-2 text-xs font-normal text-slate-400">v{s.version}</span>}</td>
                  <td className="px-3 text-right font-semibold">{c.standard_labor}</td>
                  <td className="px-3 text-right">{c.weighted_factor !== null ? `${Math.round(c.weighted_factor * 10000) / 100}%` : "—"}</td>
                  <td className="whitespace-nowrap px-3 text-xs text-slate-500">{dateVi(s.effective_from)}{s.effective_to ? ` → ${dateVi(s.effective_to)}` : ""}{s.status !== "ACTIVE" && <span className="ml-2 pg-chip bg-slate-500/20 text-slate-500">{s.status === "RETIRED" ? "Đã thay" : "Ngưng"}</span>}</td>
                  <td className="whitespace-nowrap px-3 text-right text-xs" onClick={(e) => e.stopPropagation()}>
                    {canManage && s.status === "ACTIVE" && <><button onClick={() => open(s)} className="text-brand hover:underline">Sửa</button><button onClick={() => act(() => api.post(`${RES}/labor-standards/${s.id}/deactivate`), "Đã ngưng cơ cấu.")} className="ml-3 text-slate-500 hover:underline">Ngưng</button></>}
                    {canManage && s.status === "INACTIVE" && <button onClick={() => act(() => api.post(`${RES}/labor-standards/${s.id}/activate`), "Đã áp dụng lại.")} className="text-slate-500 hover:underline">Áp dụng lại</button>}
                  </td>
                </tr>,
                ...(isOpen ? c.lines.map((l) => (
                  <tr key={`${s.id}-${l.grade}`} className="bg-slate-500/5 text-xs text-slate-600">
                    <td className="py-1 pl-10">Bậc {l.grade}</td><td className="px-3 text-right">{l.headcount}</td>
                    <td className="px-3 text-right">{l.factor !== null ? `${Math.round(l.factor * 1000) / 10}%` : "—"}</td><td />
                  </tr>
                )) : []),
              ];
            })}
            {rows.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-slate-400">{factory} chưa khai báo cơ cấu lao động theo bậc.</td></tr>}
          </tbody>
        </table>
      </div>
      {d && (
        <Modal title={d.id ? "Khai báo LĐ — sửa (tạo phiên bản mới)" : "Khai báo LĐ"} onClose={() => setD(null)}>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Xí nghiệp"><select className={input} disabled={!!d.id} value={d.factory_code} onChange={(e) => setD({ ...d, factory_code: e.target.value })}>{XNS.map((f) => <option key={f}>{f}</option>)}</select></Field>
            <Field label="Chuyền (trống = cả XN)"><input className={input} disabled={!!d.id} value={d.line} onChange={(e) => pickLine(e.target.value)} list="std-lines" data-testid="std-line" /></Field>
            <datalist id="std-lines">{rows.filter((r) => r.status === "ACTIVE" && r.line).map((r) => <option key={r.id} value={r.line} />)}</datalist>
            <Field label="Hiệu lực từ"><input type="date" className={input} value={d.effective_from} onChange={(e) => setD({ ...d, effective_from: e.target.value })} /></Field>
          </div>
          {existing && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{d?.factory_code} chuyền {d?.line} đã có cơ cấu ({existing.composition.standard_labor} người). Lưu sẽ tạo phiên bản mới thay thế bằng số liệu dưới đây. <button onClick={editExisting} className="font-semibold underline" data-testid="std-edit-existing">Nạp số người hiện có để chỉnh</button></p>}
          <table className="mt-4 w-full text-sm">
            <thead><tr className="text-xs text-slate-400"><th className="text-left">Bậc</th><th className="text-right">Hệ số (Tổng = TB)</th><th className="text-right">Số lượng (người)</th></tr></thead>
            <tbody>
              {gradeNums.map((n) => (
                <tr key={n} className="border-t border-slate-100">
                  <td className="py-1">Bậc {n}</td><td className="text-right">{Math.round(factorOf(n) * 1000) / 10}%</td>
                  <td className="text-right"><input type="number" min={0} className="w-20 rounded border border-slate-200 px-2 py-1 text-right" value={d.heads[n] ?? ""} onChange={(e) => setD({ ...d, heads: { ...d.heads, [n]: e.target.value } })} aria-label={`Số người bậc ${n}`} data-testid={`head-${n}`} /></td>
                </tr>
              ))}
              <tr className="border-t border-slate-300 font-bold"><td className="py-1">Tổng</td><td className="text-right">{total ? `${Math.round((equiv / total) * 10000) / 100}%` : "—"}</td><td className="text-right" data-testid="std-total">{total}</td></tr>
            </tbody>
          </table>
          <div className="mt-5 flex justify-end gap-2"><button onClick={() => setD(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={save} disabled={!total} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="std-save">Lưu</button></div>
        </Modal>
      )}
    </div>
  );
}
