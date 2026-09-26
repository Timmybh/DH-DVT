import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { num } from "../../lib/format";

interface Row { id: number; style_cc: string; brand: string; sot_minutes: number | null; sam_kt: number | null; sam_tt: number | null; sam_minutes: number | null; source: string; samples: number; note: string; updated_by: string }
interface Data { total: number; rows: Row[]; by_source: Record<string, number> }
const RES = "/planning/resources";
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400 whitespace-nowrap";
const SOURCE: Record<string, { label: string; cls: string }> = {
  ESTIMATE: { label: "Ước lượng", cls: "pg-adv" },
  DEFAULT: { label: "Mặc định", cls: "pg-unk" },
  ERP: { label: "ERP", cls: "pg-ok" },
  MANUAL: { label: "Nhập tay", cls: "pg-ok" },
  TRAINED: { label: "Đã huấn luyện", cls: "pg-ok" },
};

/** Thông tin sản phẩm theo mã hàng: Brand, SAM và SOT (phút chuẩn/sản phẩm). Giá trị ban đầu là ước lượng — không chuẩn, sẽ được huấn luyện/hiệu chỉnh sau. */
export default function SamPanel({ canManage }: { canManage: boolean }) {
  const [data, setData] = useState<Data>({ total: 0, rows: [], by_source: {} });
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [editId, setEditId] = useState<number | null>(null);
  const [val, setVal] = useState("");
  const [brandVal, setBrandVal] = useState("");
  const [sotVal, setSotVal] = useState("");
  const [ttVal, setTtVal] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => setData((await api.get<Data>(`${RES}/style-sam`, { params: { q: q || undefined, source: source || undefined } })).data), [q, source]);
  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })), 200);
    return () => clearTimeout(t);
  }, [load]);

  const refresh = async () => {
    setBusy(true);
    try {
      const r = (await api.post<{ added: number; estimated: number; default: number }>(`${RES}/style-sam/refresh`)).data;
      setMsg({ ok: true, text: r.added ? `Đã thêm ${r.added} mã hàng mới (${r.estimated} ước lượng, ${r.default} mặc định).` : "Không có mã hàng mới." });
      await load();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); } finally { setBusy(false); }
  };
  const save = async (r: Row) => {
    try {
      await api.put(`${RES}/style-sam/${encodeURIComponent(r.style_cc)}`, { sam_kt: val === "" ? null : Number(val), sam_tt: ttVal === "" ? null : Number(ttVal), brand: brandVal, sot_minutes: sotVal === "" ? null : Number(sotVal) });
      setEditId(null);
      setMsg({ ok: true, text: `Đã cập nhật thông tin sản phẩm ${r.style_cc}.` });
      await load();
    } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); }
  };

  return (
    <div className="space-y-3" data-testid="sam-panel">
      <p className="text-xs text-slate-500"><b>Thông tin sản phẩm</b> theo từng mã hàng: Brand, SAM và SOT (phút chuẩn cho 1 sản phẩm). Giá trị ban đầu là <b>ước lượng không chuẩn</b> (từ WORKER và CAPACITY trong kế hoạch, 480 phút, hiệu suất 85%; mã hàng chưa có số liệu dùng trung vị chung). Sẽ được huấn luyện lại sau — sửa tay khi có SAM thật.</p>
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm mã hàng / brand..." className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Tìm mã hàng" data-testid="sam-search" />
        <select value={source} onChange={(e) => setSource(e.target.value)} className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="Nguồn SAM">
          <option value="">Mọi nguồn</option>
          {Object.entries(SOURCE).map(([k, v]) => <option key={k} value={k}>{v.label}{data.by_source[k] ? ` (${data.by_source[k]})` : ""}</option>)}
        </select>
        <span className="text-xs text-slate-400">{num(data.total)} mã hàng</span>
        <span className="flex-1" />
        {canManage && <button onClick={refresh} disabled={busy} className="rounded-full border border-slate-300 px-4 py-1.5 text-xs disabled:opacity-50" data-testid="sam-refresh">Cập nhật danh sách mã hàng</button>}
      </div>
      <div className="max-h-[68vh] overflow-y-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full text-sm" data-testid="sam-table">
          <thead className="sticky top-0 bg-white"><tr><th className={th}>Mã hàng</th><th className={th}>Brand</th><th className={`${th} text-right`} title="SAM kỹ thuật — đồng bộ từ ERP">SAM KT</th><th className={`${th} text-right`} title="SAM bình quân thực tế">SAM TT</th><th className={`${th} text-right`}>SOT (phút/sp)</th><th className={`${th} text-right`}>Số dòng KH</th><th className={th}>Ghi chú</th><th className={th} /></tr></thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.id} className="border-t border-slate-100">
                <td className="px-3 py-1.5 font-mono text-xs">{r.style_cc}</td>
                <td className="px-3 text-xs">
                  {editId === r.id ? <input value={brandVal} onChange={(e) => setBrandVal(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-0.5" aria-label={`Brand ${r.style_cc}`} data-testid="brand-input" /> : (r.brand || "—")}
                </td>
                <td className="px-3 text-right font-semibold">
                  {editId === r.id
                    ? <input autoFocus type="number" step="0.01" min={0} value={val} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void save(r); if (e.key === "Escape") setEditId(null); }} className="w-24 rounded border border-slate-300 px-2 py-0.5 text-right" aria-label={`SAM KT ${r.style_cc}`} data-testid="sam-input" />
                    : (r.sam_kt !== null ? r.sam_kt : "—")}
                </td>
                <td className="px-3 text-right font-semibold">
                  {editId === r.id
                    ? <input type="number" step="0.01" min={0} value={ttVal} onChange={(e) => setTtVal(e.target.value)} className="w-24 rounded border border-slate-300 px-2 py-0.5 text-right" aria-label={`SAM TT ${r.style_cc}`} data-testid="sam-tt-input" />
                    : (r.sam_tt !== null ? r.sam_tt : "—")}
                </td>
                <td className="px-3 text-right font-semibold">
                  {editId === r.id
                    ? <input type="number" step="0.01" min={0} value={sotVal} onChange={(e) => setSotVal(e.target.value)} className="w-24 rounded border border-slate-300 px-2 py-0.5 text-right" aria-label={`SOT ${r.style_cc}`} data-testid="sot-input" />
                    : (r.sot_minutes !== null ? r.sot_minutes : "—")}
                </td>
                <td className="px-3 text-right text-xs text-slate-500">{r.samples || "—"}</td>
                <td className="max-w-[360px] truncate px-3 text-xs text-slate-400" title={r.note}>{r.note}</td>
                <td className="whitespace-nowrap px-3 text-right text-xs">
                  {canManage && (editId === r.id
                    ? <><button onClick={() => save(r)} className="text-brand hover:underline">Lưu</button><button onClick={() => setEditId(null)} className="ml-2 text-slate-500 hover:underline">Hủy</button></>
                    : <button onClick={() => { setEditId(r.id); setVal(r.sam_kt !== null ? String(r.sam_kt) : ""); setTtVal(r.sam_tt !== null ? String(r.sam_tt) : ""); setBrandVal(r.brand); setSotVal(r.sot_minutes !== null ? String(r.sot_minutes) : ""); }} className="text-brand hover:underline">Sửa</button>)}
                </td>
              </tr>
            ))}
            {data.rows.length === 0 && <tr><td colSpan={8} className="py-6 text-center text-slate-400">Chưa có mã hàng — bấm "Cập nhật danh sách mã hàng".</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
