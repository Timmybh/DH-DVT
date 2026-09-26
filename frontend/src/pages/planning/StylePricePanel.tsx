import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { dateVi, num } from "../../lib/format";

interface Row { id: number; style_cc: string; brand: string; unit_price: number; currency: string; effective_from: string; effective_to: string | null; status: string; source: string; note: string; updated_by: string }
interface Data { total: number; rows: Row[] }
const RES = "/planning/resources";
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400 whitespace-nowrap";
const inp = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
const SOURCE: Record<string, string> = { MANUAL: "Nhập tay", EXCEL: "Mẫu từ Excel" };

/** Bảng giá công ty theo mã hàng (USD/sản phẩm) có ngày hiệu lực. Đổi giá = thêm dòng mới với ngày hiệu lực mới (không ghi đè). */
export default function StylePricePanel({ canManage }: { canManage: boolean }) {
  const [data, setData] = useState<Data>({ total: 0, rows: [] });
  const [q, setQ] = useState("");
  const [hist, setHist] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ style_cc: "", unit_price: "", effective_from: today, note: "" });

  const load = useCallback(async () => setData((await api.get<Data>(`${RES}/style-prices`, { params: { q: q || undefined, include_history: hist } })).data), [q, hist]);
  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })), 200);
    return () => clearTimeout(t);
  }, [load]);

  const add = async () => {
    try {
      await api.post(`${RES}/style-prices`, { style_cc: f.style_cc, unit_price: Number(f.unit_price), effective_from: f.effective_from, note: f.note });
      setMsg({ ok: true, text: `Đã lưu giá mã hàng ${f.style_cc.toUpperCase()} hiệu lực từ ${dateVi(f.effective_from)}.` });
      setF({ ...f, style_cc: "", unit_price: "", note: "" });
      await load();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const toggle = async (r: Row) => {
    try {
      await api.post(`${RES}/style-prices/${r.id}/${r.status === "ACTIVE" ? "deactivate" : "activate"}`);
      await load();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };
  const change = (r: Row) => setF({ style_cc: r.style_cc, unit_price: String(r.unit_price), effective_from: today, note: "" });

  return (
    <div className="space-y-3" data-testid="price-panel">
      <p className="text-xs text-slate-500">Đơn giá công ty (USD/sản phẩm) theo mã hàng. Đổi giá = thêm dòng mới với <b>ngày hiệu lực</b> mới; giá áp dụng cho một ngày là dòng có ngày hiệu lực lớn nhất không sau ngày đó. Doanh thu theo tổ = sản lượng × đơn giá.</p>
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
      {canManage && (
        <div className="flex flex-wrap items-end gap-2 rounded-2xl border border-slate-200 bg-white p-3" data-testid="price-form">
          <label className="text-xs text-slate-500">Mã hàng<input className={`${inp} mt-1 block w-40`} value={f.style_cc} onChange={(e) => setF({ ...f, style_cc: e.target.value })} data-testid="price-style" /></label>
          <label className="text-xs text-slate-500">Đơn giá (USD/sp)<input type="number" step="0.001" min={0} className={`${inp} mt-1 block w-32 text-right`} value={f.unit_price} onChange={(e) => setF({ ...f, unit_price: e.target.value })} data-testid="price-value" /></label>
          <label className="text-xs text-slate-500">Hiệu lực từ ngày<input type="date" className={`${inp} mt-1 block`} value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} data-testid="price-from" /></label>
          <label className="min-w-[180px] flex-1 text-xs text-slate-500">Ghi chú<input className={`${inp} mt-1 block w-full`} value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
          <button onClick={add} disabled={!f.style_cc.trim() || !(Number(f.unit_price) > 0) || !f.effective_from} className="rounded-full bg-brand px-4 py-2 text-xs font-semibold text-white disabled:opacity-40" data-testid="price-save">Lưu giá</button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm mã hàng / brand..." className={`${inp} w-56`} aria-label="Tìm mã hàng" data-testid="price-search" />
        <label className="flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={hist} onChange={(e) => setHist(e.target.checked)} /> Hiện lịch sử giá</label>
        <span className="text-xs text-slate-400">{num(data.total)} dòng giá</span>
      </div>
      <div className="max-h-[60vh] overflow-y-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full text-sm" data-testid="price-table">
          <thead className="sticky top-0 bg-white"><tr><th className={th}>Mã hàng</th><th className={th}>Brand</th><th className={`${th} text-right`}>Đơn giá (USD)</th><th className={th}>Hiệu lực từ</th><th className={th}>Hiệu lực đến</th><th className={th}>Nguồn</th><th className={th}>Ghi chú</th><th className={th} /></tr></thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.id} className={`border-t border-slate-100 ${r.status !== "ACTIVE" ? "opacity-50" : ""}`}>
                <td className="px-3 py-1.5 font-mono text-xs">{r.style_cc}</td>
                <td className="px-3 text-xs">{r.brand || "—"}</td>
                <td className="px-3 text-right font-semibold">{r.unit_price}</td>
                <td className="whitespace-nowrap px-3 text-xs">{dateVi(r.effective_from)}</td>
                <td className="whitespace-nowrap px-3 text-xs text-slate-500">{r.effective_to ? dateVi(r.effective_to) : "Đang áp dụng"}{r.status !== "ACTIVE" && <span className="ml-2 pg-chip bg-slate-500/20 text-slate-500">Ngưng</span>}</td>
                <td className="px-3 text-xs text-slate-500">{SOURCE[r.source] ?? r.source}</td>
                <td className="max-w-[320px] truncate px-3 text-xs text-slate-400" title={r.note}>{r.note}</td>
                <td className="whitespace-nowrap px-3 text-right text-xs">
                  {canManage && r.status === "ACTIVE" && <button onClick={() => change(r)} className="text-brand hover:underline">Đổi giá</button>}
                  {canManage && <button onClick={() => toggle(r)} className="ml-3 text-slate-500 hover:underline">{r.status === "ACTIVE" ? "Ngưng" : "Áp dụng lại"}</button>}
                </td>
              </tr>
            ))}
            {data.rows.length === 0 && <tr><td colSpan={8} className="py-6 text-center text-slate-400">Chưa có giá nào.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
