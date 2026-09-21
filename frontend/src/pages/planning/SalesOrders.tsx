import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { dateVi, num } from "../../lib/format";

interface SO {
  id: number; so_number: string; description: string; customer: string; style_cc: string; model_code: string; season: string; sport: string; planned_qty: number; origin_factory: string;
  current_factory: string; window_from: string | null; window_to: string | null; current_po: string; temp_po: string; status: string; note: string; source: string; created_at: string | null; created_by: string;
}
interface Detail extends SO { identities: { id: number; type: string; value: string; source_system: string; status: string; reason: string }[]; unplanned_rows: number; version_rows: number }

const PAGE = 100;
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400 whitespace-nowrap";
const inp = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
const TYPE_LABEL: Record<string, string> = { PLAN_NOTE: "Ghi chú kế hoạch", TEMP_PO: "PO tạm", ERP_PO: "PO ERP", CUSTOMER_PO: "PO khách hàng", PREVIOUS_PO: "PO trước đây" };

export default function SalesOrders() {
  const { can } = useAuth();
  const canEdit = can("planning.edit");
  const canIssue = can("so.manage");
  const [data, setData] = useState<{ total: number; rows: SO[] }>({ total: 0, rows: [] });
  const [q, setQ] = useState("");
  const [factory, setFactory] = useState("");
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [desc, setDesc] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => setData((await api.get("/planning/so", { params: { q: q || undefined, factory: factory || undefined, limit: PAGE, offset } })).data), [q, factory, offset]);
  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })), 200);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => setOffset(0), [q, factory]);

  const open = async (id: number) => {
    const d = (await api.get<Detail>(`/planning/so/${id}`)).data;
    setDetail(d);
    setDesc(d.description);
  };
  const saveDesc = async () => {
    if (!detail) return;
    try {
      await api.put(`/planning/so/${detail.id}/description`, { description: desc });
      setMsg({ ok: true, text: "Đã cập nhật SO Description (SO Number không đổi)." });
      await Promise.all([open(detail.id), load()]);
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const bulk = async () => {
    if (!window.confirm("Cấp SO TẠM cho mọi dòng chưa có SO (Unplanned, Planned, các phiên bản)? Chạy lại an toàn, không cấp lại SO đã có.")) return;
    try {
      const r = await api.post<{ plan_rows: { issued: number; reused: number } | null; version_rows: { rows: number; issued: number } | null }>("/planning/so/bulk-issue");
      setMsg({ ok: true, text: `Đã cấp SO: dòng kế hoạch ${r.data.plan_rows?.issued ?? 0} mới / ${r.data.plan_rows?.reused ?? 0} dùng lại; dòng phiên bản ${r.data.version_rows?.rows ?? 0} (mới ${r.data.version_rows?.issued ?? 0}).` });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };

  return (
    <div className="space-y-4" data-testid="so-page">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Số SO</h1>
        <p className="text-xs text-slate-500">
          SO (<span className="font-mono">SO/YY/NNNNNN</span>) là danh tính nghiệp vụ bền vững của một đơn/nhu cầu sản xuất — cấp tự động ngay từ Unplanned, <b>không sửa</b>, không phụ thuộc PO hay xí nghiệp. PO chỉ là bí danh (ghi chú kế hoạch, PO tạm, PO ERP…).
          Chỉ <b>SO Description</b> do nghiệp vụ chỉnh. Cột SO Number / SO Description ở lưới Planned và Unplanned mặc định ẩn — bật ở nút "Cột".
        </p>
      </div>
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm SO / mô tả / khách / mã hàng / PO..." className={`${inp} w-72`} aria-label="Tìm SO" data-testid="so-search" />
        <select value={factory} onChange={(e) => setFactory(e.target.value)} className={inp} aria-label="Xí nghiệp"><option value="">Mọi XN</option>{["XN1", "XN2", "XN3"].map((f) => <option key={f}>{f}</option>)}</select>
        <span className="text-xs text-slate-400">{num(data.total)} SO</span>
        <span className="flex-1" />
        {canIssue && <button onClick={bulk} className="rounded-full border border-slate-300 px-4 py-1.5 text-xs" data-testid="so-bulk">Cấp SO tạm hàng loạt</button>}
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="rounded-lg border border-slate-200 px-3 py-1 text-xs disabled:opacity-40">‹</button>
        <span className="text-xs text-slate-500">{num(offset + 1)}–{num(Math.min(offset + PAGE, data.total))}</span>
        <button disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)} className="rounded-lg border border-slate-200 px-3 py-1 text-xs disabled:opacity-40">›</button>
      </div>
      <div className="overflow-x-auto rounded-2xl border border-slate-200">
        <table className="w-full text-sm" data-testid="so-table">
          <thead><tr><th className={th}>SO Number</th><th className={th}>SO Description</th><th className={th}>Khách</th><th className={th}>Mã hàng</th><th className={th}>Model</th><th className={th}>Mùa</th><th className={`${th} text-right`}>SL</th><th className={th}>XN hiện tại</th><th className={th}>PO / ghi chú</th><th className={th}>Nguồn</th></tr></thead>
          <tbody>
            {data.rows.map((s) => (
              <tr key={s.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-500/5" onClick={() => open(s.id)} data-testid={`so-${s.id}`}>
                <td className="whitespace-nowrap px-3 py-1.5 font-mono text-xs">{s.so_number}</td>
                <td className="max-w-[300px] truncate px-3" title={s.description}>{s.description}</td>
                <td className="px-3">{s.customer}</td><td className="px-3">{s.style_cc}</td><td className="px-3">{s.model_code}</td><td className="px-3">{s.season}</td>
                <td className="px-3 text-right">{num(s.planned_qty)}</td><td className="px-3">{s.current_factory}</td>
                <td className="max-w-[200px] truncate px-3 text-xs text-slate-500">{s.current_po || s.temp_po || s.note}</td>
                <td className="px-3 text-xs text-slate-400">{s.source === "BULK_TEMP" ? "cấp tạm" : s.source === "IMPORT" ? "import" : s.source}</td>
              </tr>
            ))}
            {data.rows.length === 0 && <tr><td colSpan={10} className="px-3 py-6 text-center text-slate-400">Chưa có SO nào.</td></tr>}
          </tbody>
        </table>
      </div>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" onClick={() => setDetail(null)}>
          <div className="max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 text-slate-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between">
              <h3 className="font-mono text-lg font-bold">{detail.so_number}</h3>
              <button onClick={() => setDetail(null)} className="text-slate-400" aria-label="Đóng">✕</button>
            </div>
            <label className="mt-3 block text-xs text-slate-500">SO Description
              <div className="mt-1 flex gap-2">
                <input value={desc} disabled={!canEdit} onChange={(e) => setDesc(e.target.value)} className={`${inp} flex-1`} aria-label="SO Description" />
                {canEdit && <button onClick={saveDesc} disabled={!desc.trim() || desc === detail.description} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-40">Lưu</button>}
              </div>
            </label>
            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
              {([["Khách hàng", detail.customer], ["Style/CC", detail.style_cc], ["Model", detail.model_code], ["Mùa", detail.season], ["Sport", detail.sport], ["SL kế hoạch", num(detail.planned_qty)],
                ["XN xuất phát", detail.origin_factory], ["XN đang thực hiện", detail.current_factory], ["Khoảng sản xuất", `${dateVi(detail.window_from)} → ${dateVi(detail.window_to)}`], ["Trạng thái", detail.status],
                ["PO hiện tại", detail.current_po || "—"], ["PO tạm", detail.temp_po || "—"], ["Ghi chú", detail.note || "—"], ["Tạo", `${detail.created_by} · ${detail.created_at ? dateVi(detail.created_at.slice(0, 10)) : ""}`],
                ["Dòng Unplanned/Planned", `${detail.unplanned_rows}`], ["Dòng trong phiên bản", `${detail.version_rows}`]] as [string, string][]).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 border-b border-slate-100 py-0.5"><dt className="text-slate-500">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
              ))}
            </dl>
            <h4 className="mt-4 text-xs font-bold uppercase text-slate-400">Bí danh PO (danh tính ngoài)</h4>
            <ul className="mt-1 space-y-1 text-sm">
              {detail.identities.map((i) => <li key={i.id} className="flex gap-2"><span className="pg-chip bg-slate-500/20 text-slate-500">{TYPE_LABEL[i.type] ?? i.type}</span><span className="font-medium">{i.value}</span><span className="text-xs text-slate-400">{i.status}</span></li>)}
              {detail.identities.length === 0 && <li className="text-xs text-slate-400">Chưa có.</li>}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
