import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { num } from "../../lib/format";

interface Row { id: number; machine_type: string; style_cc: string; output_per_day: number | null; required_quantity: number | null; source: string; effective_from: string | null; effective_to: string | null; status: string; note: string }
const RES = "/planning/resources";
const inp = "w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";

/** Đăng ký công suất (pcs/ngày/máy) của một loại máy theo từng mã hàng. Chỉ khai báo — chưa dùng trong kiểm tra Recheck. */
export default function StyleOutputPanel({ machineType, machineName, canManage }: { machineType: string | null; machineName: string; canManage: boolean }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [q, setQ] = useState("");
  const [inactive, setInactive] = useState(false);
  const [draft, setDraft] = useState({ style_cc: "", output: "", need: "", note: "" });
  const [editId, setEditId] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    if (!machineType) return setRows([]);
    setRows((await api.get<Row[]>(`${RES}/machine-style-outputs`, { params: { machine_type: machineType, q: q || undefined, include_inactive: inactive } })).data);
  }, [machineType, q, inactive]);
  useEffect(() => {
    setEditId(null);
    setDraft({ style_cc: "", output: "", need: "", note: "" });
    load().catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, [load]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      await load();
      return true;
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
      return false;
    }
  };
  const save = async () => {
    const body = { output_per_day: draft.output ? Number(draft.output) : null, required_quantity: draft.need ? Number(draft.need) : null, note: draft.note };
    const done = await act(() => (editId ? api.put(`${RES}/machine-style-outputs/${editId}`, body) : api.post(`${RES}/machine-style-outputs`, { machine_type: machineType, style_cc: draft.style_cc, ...body })),
      editId ? "Đã cập nhật công suất." : "Đã đăng ký công suất.");
    if (done) { setEditId(null); setDraft({ style_cc: "", output: "", need: "", note: "" }); }
  };

  return (
    <aside className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4" data-testid="style-output-panel">
      <div>
        <h3 className="text-sm font-bold text-slate-900">Công suất theo mã hàng</h3>
        <p className="text-xs text-slate-500">{machineType ? <>Loại máy <b>{machineType}</b> {machineName}. Công suất (pcs/ngày/máy) và số máy cần khi chạy từng mã hàng.</> : "Chọn một loại máy ở danh sách bên trái để đăng ký công suất theo mã hàng."}</p>
      </div>
      {machineType && (
        <>
          {msg && <p className={`rounded-lg border px-2 py-1.5 text-xs ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
          {canManage && (
            <div className="grid grid-cols-[1fr_92px_72px] gap-2">
              <input className={inp} value={draft.style_cc} disabled={!!editId} onChange={(e) => setDraft({ ...draft, style_cc: e.target.value })} placeholder="Mã hàng (Style/CC)" aria-label="Mã hàng" data-testid="so-style" />
              <input className={inp} type="number" min={0} value={draft.output} onChange={(e) => setDraft({ ...draft, output: e.target.value })} placeholder="Công suất/ngày" aria-label="Công suất/ngày" data-testid="so-output" />
              <input className={inp} type="number" min={0} value={draft.need} onChange={(e) => setDraft({ ...draft, need: e.target.value })} placeholder="Số máy" aria-label="Số máy cần" data-testid="so-need" />
              <input className={`${inp} col-span-3`} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} placeholder="Ghi chú (không bắt buộc)" aria-label="Ghi chú" />
              <div className="col-span-3 flex justify-end gap-2">
                {editId && <button onClick={() => { setEditId(null); setDraft({ style_cc: "", output: "", need: "", note: "" }); }} className="rounded-full border border-slate-300 px-3 py-1 text-xs">Hủy sửa</button>}
                <button onClick={save} disabled={!draft.style_cc.trim() || !(Number(draft.output) > 0 || Number(draft.need) > 0)} className="rounded-full bg-brand px-4 py-1 text-xs font-semibold text-white disabled:opacity-40" data-testid="so-save">{editId ? "Lưu sửa" : "Đăng ký"}</button>
              </div>
            </div>
          )}
          <div className="flex items-center gap-2">
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm mã hàng..." className={inp} aria-label="Tìm mã hàng" />
            <label className="flex items-center gap-1 whitespace-nowrap text-xs text-slate-500"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} /> Cả đã ngưng</label>
          </div>
          <div className="max-h-[52vh] overflow-y-auto">
            <table className="w-full text-sm" data-testid="style-output-table">
              <thead><tr className="text-[11px] uppercase text-slate-400"><th className="py-1 text-left">Mã hàng</th><th className="text-right">Công suất/ngày</th><th className="text-right">Số máy</th><th /></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={`border-t border-slate-100 ${r.status === "INACTIVE" ? "opacity-50" : ""}`}>
                    <td className="py-1" title={r.note}>{r.style_cc}{r.source === "QTCN" && <span className="ml-1 text-[10px] text-slate-400">QTCN</span>}</td><td className="text-right font-semibold">{r.output_per_day ? num(r.output_per_day) : "—"}</td><td className="text-right">{r.required_quantity ?? "—"}</td>
                    <td className="whitespace-nowrap pl-2 text-right text-xs">{canManage && (r.status === "ACTIVE"
                      ? <><button onClick={() => { setEditId(r.id); setDraft({ style_cc: r.style_cc, output: r.output_per_day ? String(r.output_per_day) : "", need: r.required_quantity ? String(r.required_quantity) : "", note: r.note }); }} className="text-brand hover:underline">Sửa</button>
                        <button onClick={() => act(() => api.post(`${RES}/machine-style-outputs/${r.id}/deactivate`, { reason: "" }), "Đã ngưng.")} className="ml-2 text-slate-500 hover:underline">Ngưng</button></>
                      : <button onClick={() => act(() => api.post(`${RES}/machine-style-outputs/${r.id}/activate`, { reason: "" }), "Đã áp dụng lại.")} className="text-slate-500 hover:underline">Áp dụng lại</button>)}</td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={4} className="py-4 text-center text-xs text-slate-400">Chưa đăng ký công suất cho mã hàng nào.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </aside>
  );
}
